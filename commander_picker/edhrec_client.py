"""Fetch and cache EDHREC commander-list pages by color identity.

EDHREC has no official public API, but its own frontend consumes JSON
documents from ``json.edhrec.com`` that mirror what's rendered on each
commander-list page. This module fetches those per-color-identity pages
and caches them locally instead of re-fetching on every session.

**Known gap** (see PLAN.md): this dev environment's egress policy
blocks edhrec.com, so the exact URL template and response shape below
are unverified against a live response — built from public knowledge of
EDHREC's JSON API pattern and cross-checked against the offline test
fixture. Whoever runs this with real network access should run
``commander-picker update-data`` once and sanity-check the resulting
``data/commanders.db`` (row counts, spot-check a few well-known
commanders), then fix up ``PAGE_URL_TEMPLATE`` / the parser in
``db.py`` if the real shape differs.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from commander_picker.colors import all_slugs
from commander_picker.themes import THEME_SLUGS

COLOR_PAGE_URL_TEMPLATE = "https://json.edhrec.com/pages/commanders/{slug}.json"
THEME_PAGE_URL_TEMPLATE = "https://json.edhrec.com/pages/themes/{slug}.json"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EDHREC_DIR = DATA_DIR / "edhrec"
META_PATH = DATA_DIR / "edhrec_meta.json"

# Cache keys are prefixed so a color slug and a theme slug can't collide
# (e.g. a hypothetical color combo and theme sharing a name).
_COLOR_PREFIX = "color__"
_THEME_PREFIX = "theme__"

# EDHREC's own data updates roughly daily; matches the cadence
# commander-synergy uses for Scryfall bulk data.
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60

USER_AGENT = "commander-picker/0.1 (+https://github.com/steven-robert-eddy/commander-picker)"
REQUEST_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json;q=0.9,*/*;q=0.8"}

# Be a polite, cache-first client: this is a public site's data
# endpoint, not an official API. Small delay between page fetches when
# pulling multiple slugs in one run.
REQUEST_DELAY_SECONDS = 0.5


class EdhrecFetchError(RuntimeError):
    pass


@dataclass
class FetchResult:
    slug: str
    kind: str
    path: Path
    from_cache: bool


def _cache_key(kind: str, slug: str) -> str:
    prefix = _COLOR_PREFIX if kind == "color" else _THEME_PREFIX
    return f"{prefix}{slug}"


def _page_path(kind: str, slug: str) -> Path:
    return EDHREC_DIR / f"{_cache_key(kind, slug)}.json"


def _url_for(kind: str, slug: str) -> str:
    template = COLOR_PAGE_URL_TEMPLATE if kind == "color" else THEME_PAGE_URL_TEMPLATE
    return template.format(slug=slug)


def _read_meta() -> dict:
    if not META_PATH.exists():
        return {}
    try:
        return json.loads(META_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_meta(meta: dict) -> None:
    META_PATH.write_text(json.dumps(meta, indent=2))


def _cache_is_fresh(cache_key: str, path: Path, meta: dict, max_age_seconds: int) -> bool:
    if not path.exists():
        return False
    fetched_at = meta.get(cache_key, {}).get("fetched_at")
    if fetched_at is None:
        return False
    return (time.time() - fetched_at) < max_age_seconds


def _fetch_page(kind: str, slug: str, force: bool, max_age_seconds: int) -> FetchResult:
    EDHREC_DIR.mkdir(parents=True, exist_ok=True)
    meta = _read_meta()
    cache_key = _cache_key(kind, slug)
    path = _page_path(kind, slug)

    if not force and _cache_is_fresh(cache_key, path, meta, max_age_seconds):
        return FetchResult(slug=slug, kind=kind, path=path, from_cache=True)

    url = _url_for(kind, slug)
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise EdhrecFetchError(f"Failed to fetch EDHREC {kind} page for {slug!r} ({url}): {exc}") from exc

    path.write_text(json.dumps(payload))
    meta[cache_key] = {"fetched_at": time.time(), "url": url}
    _write_meta(meta)

    return FetchResult(slug=slug, kind=kind, path=path, from_cache=False)


def fetch_color_page(slug: str, force: bool = False, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS) -> FetchResult:
    """Ensure the cached JSON page for a color-identity slug exists and is fresh."""
    return _fetch_page("color", slug, force, max_age_seconds)


def fetch_theme_page(slug: str, force: bool = False, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS) -> FetchResult:
    """Ensure the cached JSON page for a theme/archetype slug exists and is fresh."""
    return _fetch_page("theme", slug, force, max_age_seconds)


def fetch_all_pages(
    force: bool = False,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    color_slugs: list[str] | None = None,
    theme_slugs: list[str] | None = None,
) -> list[FetchResult]:
    """Fetch (or reuse cached) pages for every color-identity and theme slug."""
    results = []
    for slug in color_slugs or all_slugs():
        result = fetch_color_page(slug, force=force, max_age_seconds=max_age_seconds)
        results.append(result)
        if not result.from_cache:
            time.sleep(REQUEST_DELAY_SECONDS)
    for slug in theme_slugs or THEME_SLUGS:
        result = fetch_theme_page(slug, force=force, max_age_seconds=max_age_seconds)
        results.append(result)
        if not result.from_cache:
            time.sleep(REQUEST_DELAY_SECONDS)
    return results


def page_exists(kind: str, slug: str) -> bool:
    """Whether a cached page exists on disk for this slug, regardless of freshness."""
    return _page_path(kind, slug).exists()


def load_page(kind: str, slug: str) -> dict:
    """Load a cached page's JSON from disk."""
    path = _page_path(kind, slug)
    if not path.exists():
        raise EdhrecFetchError(
            f"No cached {kind} page for {slug!r}. Run `commander-picker update-data` first."
        )
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
