from __future__ import annotations

import argparse
import sys
import time

from commander_picker import db, edhrec_client, elo, pool, scryfall_client, sessions
from commander_picker.colors import all_slugs
from commander_picker.themes import THEME_SLUGS


def _cmd_update_data(args: argparse.Namespace) -> int:
    color_slugs = args.colors.split(",") if args.colors else None
    theme_slugs = args.themes.split(",") if args.themes else None

    print("Fetching EDHREC pages...")
    results, failures = edhrec_client.fetch_all_pages(
        force=args.force,
        color_slugs=color_slugs,
        theme_slugs=theme_slugs,
    )
    fetched = sum(1 for r in results if not r.from_cache)
    cached = len(results) - fetched
    print(f"  {fetched} fetched, {cached} served from cache ({len(results)} pages total)")
    if failures:
        color_failures = [f for f in failures if f.kind == "color"]
        theme_failures = [f for f in failures if f.kind == "theme"]
        if color_failures:
            print(f"  warning: {len(color_failures)} color page(s) failed:", file=sys.stderr)
            for f in color_failures:
                print(f"    {f.slug}: {f.error}", file=sys.stderr)
        if theme_failures:
            # THEME_SLUGS is verified live (see themes.py), but EDHREC
            # can still rename/remove a tag later -- surface it rather
            # than aborting the whole run.
            print(
                f"  note: {len(theme_failures)} theme slug(s) skipped (not found on EDHREC): "
                + ", ".join(f.slug for f in theme_failures)
            )

    image_lookup = None
    card_meta_lookup = None
    if not args.skip_images:
        print("Fetching Scryfall card details...")
        try:
            oracle_path = scryfall_client.fetch_oracle_cards(force=args.force)
            image_lookup = scryfall_client.build_image_lookup(oracle_path)
            card_meta_lookup = scryfall_client.build_card_meta_lookup(oracle_path)
            print(f"  {len(image_lookup)} card images, {len(card_meta_lookup)} card details available")
        except scryfall_client.ScryfallFetchError as exc:
            print(f"  warning: couldn't fetch card details ({exc}) -- continuing without them", file=sys.stderr)

    print("Building data/commanders.db...")
    try:
        path = db.build_database(
            color_slugs=color_slugs,
            theme_slugs=theme_slugs,
            image_lookup=image_lookup,
            card_meta_lookup=card_meta_lookup,
        )
    except db.DbError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"  wrote {path}")
    return 0


def _cmd_enrich_commanders(args: argparse.Namespace) -> int:
    """Fetch+cache each commander's own EDHREC detail page (salt score,
    richer per-commander tags) -- see edhrec_client.fetch_commander_detail_page.

    Deliberately only touches edhrec_client's on-disk JSON cache, never
    commanders.db directly -- `update-data` rebuilds commanders.db from
    scratch every time, so writing enrichment straight into it would get
    silently wiped by the next ordinary update-data run. Run
    `commander-picker update-data` after this to fold the newly cached
    detail pages in (mirrors the fetch-then-build split update-data
    already does internally for color/theme pages).
    """
    try:
        conn = db.connect()
    except db.DbError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        rows = conn.execute("SELECT name, sanitized FROM commanders ORDER BY name").fetchall()
    finally:
        conn.close()

    fetched = 0
    skipped = 0
    failed = 0
    for name, sanitized in ((row["name"], row["sanitized"]) for row in rows):
        if not sanitized:
            continue
        if not args.force and edhrec_client.page_exists("commander", sanitized):
            skipped += 1
            continue
        if args.limit is not None and fetched >= args.limit:
            break
        try:
            edhrec_client.fetch_commander_detail_page(sanitized, force=args.force)
        except edhrec_client.EdhrecFetchError as exc:
            print(f"  warning: {name} ({sanitized}): {exc}", file=sys.stderr)
            failed += 1
            continue
        fetched += 1
        if fetched % 50 == 0:
            print(f"  ...{fetched} fetched so far")
        time.sleep(edhrec_client.REQUEST_DELAY_SECONDS)

    print(f"Done: {fetched} fetched, {skipped} already cached, {failed} failed.")
    if fetched:
        print("Run `commander-picker update-data` to fold the newly cached detail pages into commanders.db.")
    return 0


def _cmd_pool(args: argparse.Namespace) -> int:
    filters = _filters_from_args(args)

    try:
        conn = db.connect()
    except db.DbError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        candidates = pool.build_pool(
            conn,
            filters,
            max_pool_size=args.pool_size,
            min_pool_size=args.min_pool_size,
        )
    except pool.PoolTooSmallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    candidates.sort(key=lambda c: c.num_decks, reverse=True)
    print(f"{len(candidates)} candidate(s):")
    for c in candidates:
        theme_str = f" [{', '.join(c.themes)}]" if c.themes else ""
        color_display = c.color_identity or "C"
        print(f"  {c.name} ({color_display}, {c.num_decks} decks){theme_str}")
    return 0


def _filters_from_args(args: argparse.Namespace) -> pool.PoolFilters:
    themes = tuple(args.themes.split(",")) if args.themes else ()
    return pool.PoolFilters(
        colors=args.colors,
        color_mode=args.color_mode,
        max_decks=args.max_decks,
        min_decks=args.min_decks,
        themes=themes,
        themes_mode=args.themes_mode,
        max_price=args.max_price,
    )


def _print_rankings(ranked: list[sessions.RankedCommander], limit: int | None = None) -> None:
    shown = ranked[:limit] if limit else ranked
    for i, c in enumerate(shown, start=1):
        color_display = c.color_identity or "C"
        print(f"  {i}. {c.name} ({color_display}, {c.num_decks} decks) -- rating {c.rating:.0f}")
    if limit and len(ranked) > limit:
        print(f"  ... and {len(ranked) - limit} more")


def _interactive_loop(conn: object, session_id: str) -> None:
    while True:
        info = sessions.get_session(conn, session_id)
        if info.status != "active":
            # Reached target_rounds -- record_pick/next_pairing auto-finish
            # the session at that point now, no more open-ended play past
            # the round count with no visible stopping point.
            print("\nFinished! Final ranking:")
            _print_rankings(sessions.get_rankings(conn, session_id))
            return

        pairing = sessions.next_pairing(conn, session_id)
        if pairing is None:
            print("Session is no longer active.")
            break

        a, b = pairing
        candidate_info = {
            r["commander_name"]: r
            for r in conn.execute(
                "SELECT * FROM candidates WHERE session_id = ? AND commander_name IN (?, ?)",
                (session_id, a, b),
            ).fetchall()
        }
        print(f"\nRound {info.rounds_completed + 1} of {info.target_rounds}:")
        for i, name in enumerate((a, b), start=1):
            row = candidate_info[name]
            color_display = row["color_identity"] or "C"
            print(f"  [{i}] {name} ({color_display}, {row['num_decks']} decks)")

        try:
            choice = input("Pick 1 or 2 ('u' to undo last pick, 'f' to finish early, 'q' to pause): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nPaused.")
            break

        if choice in ("q", "quit"):
            print("Paused.")
            break
        if choice in ("f", "finish", "done"):
            sessions.finish_session(conn, session_id)
            print("\nFinished! Final ranking:")
            _print_rankings(sessions.get_rankings(conn, session_id))
            return
        if choice in ("u", "undo"):
            try:
                sessions.undo_last_pick(conn, session_id)
                print("Undone.")
            except sessions.SessionError as exc:
                print(f"error: {exc}")
            continue
        if choice not in ("1", "2"):
            print("Please enter 1, 2, u, f, or q.")
            continue

        winner, loser = (a, b) if choice == "1" else (b, a)
        sessions.record_pick(conn, session_id, winner, loser)

    print(f"Resume later with: commander-picker resume {session_id}")
    print("Current standings:")
    _print_rankings(sessions.get_rankings(conn, session_id), limit=10)


def _print_bracket(bracket: sessions.BracketState) -> None:
    total_rounds = len(bracket.rounds)
    for i, round_matches in enumerate(bracket.rounds, start=1):
        print(f"{elo.bracket_round_label(i, total_rounds)}:")
        for m in round_matches:
            a = m.seed_a or "TBD"
            b = m.seed_b or "TBD"
            a_display = f"{a} (won)" if m.winner and m.winner == m.seed_a else a
            b_display = f"{b} (won)" if m.winner and m.winner == m.seed_b else b
            suffix = "" if m.winner else " -- TBD"
            print(f"  {a_display} vs {b_display}{suffix}")
    if bracket.champion:
        print(f"\nChampion: {bracket.champion}")


def _interactive_bracket_loop(conn: object, session_id: str) -> None:
    while True:
        info = sessions.get_session(conn, session_id)
        if info.status != "active":
            print("\nBracket complete!")
            _print_bracket(sessions.get_bracket(conn, session_id))
            return

        match = sessions.next_bracket_match(conn, session_id)
        if match is None:
            print("Session is no longer active.")
            break

        round_num, _slot, a, b = match
        candidate_info = {
            r["commander_name"]: r
            for r in conn.execute(
                "SELECT * FROM candidates WHERE session_id = ? AND commander_name IN (?, ?)",
                (session_id, a, b),
            ).fetchall()
        }
        print(f"\n{elo.bracket_round_label(round_num, info.target_rounds)}:")
        for i, name in enumerate((a, b), start=1):
            row = candidate_info[name]
            color_display = row["color_identity"] or "C"
            print(f"  [{i}] {name} ({color_display}, {row['num_decks']} decks)")

        try:
            choice = input("Pick 1 or 2 ('q' to pause): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nPaused.")
            break

        if choice in ("q", "quit"):
            print("Paused.")
            break
        if choice not in ("1", "2"):
            print("Please enter 1, 2, or q.")
            continue

        winner, loser = (a, b) if choice == "1" else (b, a)
        sessions.record_bracket_pick(conn, session_id, winner, loser)

    print(f"Resume later with: commander-picker resume {session_id}")


def _cmd_play(args: argparse.Namespace) -> int:
    filters = _filters_from_args(args)
    mode = args.mode

    if mode == "bracket" and not elo.is_valid_bracket_size(args.pool_size):
        print(
            f"error: bracket mode needs --pool-size to be a power of two (4, 8, 16, ...) -- got {args.pool_size}",
            file=sys.stderr,
        )
        return 1

    try:
        catalog_conn = db.connect()
    except db.DbError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Bracket mode forces min_pool_size up to exactly pool_size -- build_pool
    # only ever trims a larger match set down to max_pool_size, it never
    # tops up a smaller one, so without this a bracket could silently get
    # built with fewer candidates than requested, failing
    # elo.is_valid_bracket_size inside create_session instead of giving a
    # clear "not enough candidates" error here.
    min_pool_size = args.pool_size if mode == "bracket" else args.min_pool_size
    try:
        candidates = pool.build_pool(
            catalog_conn,
            filters,
            max_pool_size=args.pool_size,
            min_pool_size=min_pool_size,
        )
    except pool.PoolTooSmallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        catalog_conn.close()

    session_conn = sessions.connect()
    session_id = sessions.create_session(
        session_conn, candidates, description=pool.describe_filters(filters), mode=mode
    )
    info = sessions.get_session(session_conn, session_id)
    print(f"Started session {session_id} with {info.pool_size} candidates ({pool.describe_filters(filters)}).")

    if mode == "bracket":
        print(f"Single-elimination bracket -- {info.target_rounds} round(s) to a champion.")
        _interactive_bracket_loop(session_conn, session_id)
    else:
        print(f"{info.target_rounds} rounds -- pick your favorite each round ('f' to finish early).")
        _interactive_loop(session_conn, session_id)
    session_conn.close()
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    session_conn = sessions.connect()
    try:
        info = sessions.get_session(session_conn, args.session_id)
    except sessions.SessionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if info.status != "active":
        print(f"Session {args.session_id} is {info.status}, not active. Final results:")
        if info.mode == "bracket":
            _print_bracket(sessions.get_bracket(session_conn, args.session_id))
        else:
            _print_rankings(sessions.get_rankings(session_conn, args.session_id))
        return 0

    print(f"Resuming session {args.session_id} ({info.rounds_completed}/{info.target_rounds} rounds so far).")
    if info.mode == "bracket":
        _interactive_bracket_loop(session_conn, args.session_id)
    else:
        _interactive_loop(session_conn, args.session_id)
    session_conn.close()
    return 0


def _cmd_sessions(_args: argparse.Namespace) -> int:
    conn = sessions.connect()
    all_sessions = sessions.list_sessions(conn)
    if not all_sessions:
        print("No sessions yet. Start one with: commander-picker play")
        return 0
    for s in all_sessions:
        print(
            f"{s.id}  [{s.status}]  [{s.mode}]  {s.rounds_completed}/{s.target_rounds} rounds  "
            f"{s.pool_size} candidates  {s.description}"
        )
    return 0


def _cmd_results(args: argparse.Namespace) -> int:
    conn = sessions.connect()
    try:
        info = sessions.get_session(conn, args.session_id)
    except sessions.SessionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if info.mode == "bracket":
        _print_bracket(sessions.get_bracket(conn, args.session_id))
    else:
        _print_rankings(sessions.get_rankings(conn, args.session_id))
    return 0


def _cmd_leaderboard(args: argparse.Namespace) -> int:
    conn = sessions.connect()

    if args.reset:
        if not args.yes:
            answer = input(
                "This permanently erases every commander's all-time rating and "
                "games-played count (session history itself is unaffected). "
                "Type 'yes' to confirm: "
            ).strip().lower()
            if answer != "yes":
                print("Cancelled.")
                return 0
        sessions.reset_leaderboard(conn)
        print("All-time leaderboard reset.")
        return 0

    ranked = sessions.get_leaderboard(conn, limit=args.limit, colors=args.colors, color_mode=args.color_mode)
    if not ranked:
        if args.colors:
            print("No commanders match that color filter yet.")
        else:
            print("No all-time ratings yet -- play a session with `commander-picker play` first.")
        return 0
    for i, c in enumerate(ranked, start=1):
        color_display = c.color_identity or "C"
        games = "1 game" if c.games_played == 1 else f"{c.games_played} games"
        print(f"  {i}. {c.name} ({color_display}, {c.num_decks} decks) -- rating {c.rating:.0f} ({games})")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        db.connect()
    except db.DbError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    import uvicorn

    uvicorn.run("commander_picker.web.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _cmd_list_colors(_args: argparse.Namespace) -> int:
    for slug in all_slugs():
        print(slug)
    return 0


def _cmd_list_themes(_args: argparse.Namespace) -> int:
    for slug in THEME_SLUGS:
        print(slug)
    return 0


def _add_pool_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--colors", help="allowed colors, e.g. BRG (default: no color filter)")
    parser.add_argument(
        "--color-mode",
        choices=["subset", "exact"],
        default="subset",
        help="'subset' (commander's colors fit within --colors) or 'exact' match (default: subset)",
    )
    parser.add_argument("--max-decks", type=int, default=pool.DEFAULT_MAX_DECKS, help="deck-count ceiling (default: 10000)")
    parser.add_argument("--min-decks", type=int, default=pool.DEFAULT_MIN_DECKS, help="deck-count floor (default: 100)")
    parser.add_argument(
        "--max-price",
        type=float,
        default=None,
        help="USD price ceiling, from Scryfall data (default: no price filter). "
        "Commanders with no price data are never excluded by this.",
    )
    parser.add_argument("--themes", help="comma-separated theme slugs to filter by (default: none)")
    parser.add_argument(
        "--themes-mode",
        choices=["any", "all"],
        default="any",
        help="match ANY or ALL of --themes (default: any)",
    )
    parser.add_argument("--pool-size", type=int, default=pool.DEFAULT_MAX_POOL_SIZE, help="max candidates to return (default: 40)")
    parser.add_argument("--min-pool-size", type=int, default=pool.DEFAULT_MIN_POOL_SIZE, help="error if fewer than this many match (default: 4)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="commander-picker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser("update-data", help="fetch EDHREC pages and rebuild the local DB")
    update.add_argument("--force", action="store_true", help="bypass the freshness cache")
    update.add_argument("--colors", help="comma-separated color slugs to fetch (default: all)")
    update.add_argument("--themes", help="comma-separated theme slugs to fetch (default: all)")
    update.add_argument(
        "--skip-images",
        action="store_true",
        help="skip fetching Scryfall card details (images, mana cost, type line, price)",
    )
    update.set_defaults(func=_cmd_update_data)

    enrich = subparsers.add_parser(
        "enrich-commanders",
        help="fetch+cache each commander's own EDHREC detail page (salt score, richer tags)",
    )
    enrich.add_argument(
        "--limit", type=int, default=None, help="stop after this many NEW fetches (default: unbounded)"
    )
    enrich.add_argument("--force", action="store_true", help="bypass the freshness cache")
    enrich.set_defaults(func=_cmd_enrich_commanders)

    pool_cmd = subparsers.add_parser("pool", help="preview a filtered candidate pool")
    _add_pool_filter_args(pool_cmd)
    pool_cmd.set_defaults(func=_cmd_pool)

    play = subparsers.add_parser("play", help="start a new picker session and play it interactively")
    _add_pool_filter_args(play)
    play.add_argument(
        "--mode",
        choices=["duel", "bracket"],
        default="duel",
        help="'duel' (continuous rating-adjacent swiping, default) or 'bracket' "
        "(single-elimination tournament to one champion -- needs --pool-size to be a power of two)",
    )
    play.set_defaults(func=_cmd_play)

    resume = subparsers.add_parser("resume", help="resume a paused picker session")
    resume.add_argument("session_id")
    resume.set_defaults(func=_cmd_resume)

    sessions_cmd = subparsers.add_parser("sessions", help="list all picker sessions")
    sessions_cmd.set_defaults(func=_cmd_sessions)

    results = subparsers.add_parser("results", help="show the current/final ranking for a session")
    results.add_argument("session_id")
    results.set_defaults(func=_cmd_results)

    leaderboard = subparsers.add_parser(
        "leaderboard", help="show the all-time Elo ranking, built up across every session ever played"
    )
    leaderboard.add_argument("--limit", type=int, default=25, help="max entries to show (default: 25)")
    leaderboard.add_argument("--colors", help="only show commanders whose colors match, e.g. BRG (default: no filter)")
    leaderboard.add_argument(
        "--color-mode",
        choices=["subset", "exact"],
        default="subset",
        help="'subset' (commander's colors fit within --colors) or 'exact' match (default: subset)",
    )
    leaderboard.add_argument(
        "--reset", action="store_true", help="permanently erase all-time ratings (asks for confirmation)"
    )
    leaderboard.add_argument("--yes", action="store_true", help="skip the confirmation prompt for --reset")
    leaderboard.set_defaults(func=_cmd_leaderboard)

    list_colors = subparsers.add_parser("list-colors", help="print all known color-identity slugs")
    list_colors.set_defaults(func=_cmd_list_colors)

    list_themes = subparsers.add_parser("list-themes", help="print all known theme slugs")
    list_themes.set_defaults(func=_cmd_list_themes)

    serve = subparsers.add_parser("serve", help="run the web UI (FastAPI + browser frontend)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="auto-restart on code changes (development)")
    serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
