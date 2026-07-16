from __future__ import annotations

import argparse
import sys

from commander_picker import db, edhrec_client, pool
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
            # Expected to happen sometimes -- THEME_SLUGS is an unverified
            # guess of which tag slugs actually exist on EDHREC.
            print(
                f"  note: {len(theme_failures)} theme slug(s) skipped (not found on EDHREC): "
                + ", ".join(f.slug for f in theme_failures)
            )

    print("Building data/commanders.db...")
    try:
        path = db.build_database(color_slugs=color_slugs, theme_slugs=theme_slugs)
    except db.DbError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"  wrote {path}")
    return 0


def _cmd_pool(args: argparse.Namespace) -> int:
    themes = tuple(args.themes.split(",")) if args.themes else ()
    filters = pool.PoolFilters(
        colors=args.colors,
        color_mode=args.color_mode,
        max_decks=args.max_decks,
        min_decks=args.min_decks,
        themes=themes,
        themes_mode=args.themes_mode,
    )

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
        print(f"  {c.name} ({c.color_identity}, {c.num_decks} decks){theme_str}")
    return 0


def _cmd_list_colors(_args: argparse.Namespace) -> int:
    for slug in all_slugs():
        print(slug)
    return 0


def _cmd_list_themes(_args: argparse.Namespace) -> int:
    for slug in THEME_SLUGS:
        print(slug)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="commander-picker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser("update-data", help="fetch EDHREC pages and rebuild the local DB")
    update.add_argument("--force", action="store_true", help="bypass the freshness cache")
    update.add_argument("--colors", help="comma-separated color slugs to fetch (default: all)")
    update.add_argument("--themes", help="comma-separated theme slugs to fetch (default: all)")
    update.set_defaults(func=_cmd_update_data)

    pool_cmd = subparsers.add_parser("pool", help="preview a filtered candidate pool")
    pool_cmd.add_argument("--colors", help="allowed colors, e.g. BRG (default: no color filter)")
    pool_cmd.add_argument(
        "--color-mode",
        choices=["subset", "exact"],
        default="subset",
        help="'subset' (commander's colors fit within --colors) or 'exact' match (default: subset)",
    )
    pool_cmd.add_argument("--max-decks", type=int, default=pool.DEFAULT_MAX_DECKS, help="deck-count ceiling (default: 10000)")
    pool_cmd.add_argument("--min-decks", type=int, default=None, help="deck-count floor (default: none)")
    pool_cmd.add_argument("--themes", help="comma-separated theme slugs to filter by (default: none)")
    pool_cmd.add_argument(
        "--themes-mode",
        choices=["any", "all"],
        default="any",
        help="match ANY or ALL of --themes (default: any)",
    )
    pool_cmd.add_argument("--pool-size", type=int, default=pool.DEFAULT_MAX_POOL_SIZE, help="max candidates to return (default: 40)")
    pool_cmd.add_argument("--min-pool-size", type=int, default=pool.DEFAULT_MIN_POOL_SIZE, help="error if fewer than this many match (default: 4)")
    pool_cmd.set_defaults(func=_cmd_pool)

    list_colors = subparsers.add_parser("list-colors", help="print all known color-identity slugs")
    list_colors.set_defaults(func=_cmd_list_colors)

    list_themes = subparsers.add_parser("list-themes", help="print all known theme slugs")
    list_themes.set_defaults(func=_cmd_list_themes)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
