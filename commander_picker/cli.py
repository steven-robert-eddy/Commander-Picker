from __future__ import annotations

import argparse
import sys

from commander_picker import db, edhrec_client
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
