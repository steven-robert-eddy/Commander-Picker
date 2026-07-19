"""Fetch and cache EDHREC commander-list pages by color identity.

EDHREC has no official public API, but its own frontend consumes JSON
documents from ``json.edhrec.com`` that mirror what's rendered on each
commander-list page. This module fetches those per-color-identity pages
and caches them locally instead of re-fetching on every session.

Both URL templates below are **verified 2026-07-16** against live
responses (fetched by hand from an unrestricted network — this dev
sandbox's own egress policy still blocks edhrec.com directly, see
PLAN.md). Notably, EDHREC calls archetype/theme pages "tags"
internally (``/pages/tags/<slug>.json``), not "themes" — the initial
``/pages/themes/...`` guess 403'd against the real server.

A first-page cardlist only holds its first ~100 entries and, if there
are more, carries a ``more`` field (a relative path) pointing at a
continuation page. Continuation pages have a **different shape** than
the first page — flat ``{"cardviews": [...], "is_paginated": bool,
"more": "..."}`` rather than wrapped in ``container.json_dict``,
verified live 2026-07-16 against a real second Rakdos page. Pagination
is followed until either a page's lowest ``num_decks`` drops below
``MIN_DECKS_FLOOR`` or ``MAX_CONTINUATION_PAGES`` is hit, whichever
comes first — a deliberate choice (confirmed with the user) not to
chase single-digit-deck commanders into dozens of requests per color.
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
THEME_PAGE_URL_TEMPLATE = "https://json.edhrec.com/pages/tags/{slug}.json"
CONTINUATION_BASE_URL = "https://json.edhrec.com/pages/"

# Pagination stopping rules (see module docstring): whichever hits first.
MIN_DECKS_FLOOR = 50
MAX_CONTINUATION_PAGES = 15

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EDHREC_DIR = DATA_DIR / "edhrec"
META_PATH = DATA_DIR / "edhrec_meta.json"

# Cache keys are prefixed so a color slug and a theme slug can't collide
# (e.g. a hypothetical color combo and theme sharing a name).
_COLOR_PREFIX = "color__"
_THEME_PREFIX = "theme__"
_COMMANDER_PREFIX = "commander__"

_CACHE_PREFIXES = {"color": _COLOR_PREFIX, "theme": _THEME_PREFIX, "commander": _COMMANDER_PREFIX}

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
    return f"{_CACHE_PREFIXES[kind]}{slug}"


def _page_path(kind: str, slug: str) -> Path:
    return EDHREC_DIR / f"{_cache_key(kind, slug)}.json"


def _url_for(kind: str, slug: str) -> str:
    # "commander" (an individual commander's detail page) shares the same
    # URL template as "color" -- EDHREC uses one route,
    # /pages/commanders/<slug>.json, for both a color-combo slug (e.g.
    # "rakdos") and a specific commander's own slug (e.g.
    # "rakdos-lord-of-riots"). Verified live 2026-07-19.
    template = THEME_PAGE_URL_TEMPLATE if kind == "theme" else COLOR_PAGE_URL_TEMPLATE
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


def _get_json(url: str, error_context: str) -> dict:
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        raise EdhrecFetchError(f"Failed to fetch {error_context} ({url}): {exc}") from exc


def _paginate_cardlist(cardlist: dict) -> None:
    """Follow one cardlist's `more` pagination chain in place, merging
    continuation pages' cardviews into it. See module docstring for the
    stopping rules and the continuation-page shape.

    Only called for cardlists that already have a `more` field, i.e.
    only when there's an actual decision to fetch further pages. A
    cardlist whose first page already ends below MIN_DECKS_FLOOR with
    no `more` field at all (a naturally short list, e.g. a niche color
    combo) is left untouched -- no extra request needed, so no reason
    to throw that data away.
    """
    cardlist.setdefault("cardviews", [])
    pages_fetched = 0
    while cardlist.get("more") and pages_fetched < MAX_CONTINUATION_PAGES:
        more_path = cardlist.pop("more")
        page = _get_json(f"{CONTINUATION_BASE_URL}{more_path}", "EDHREC continuation page")
        pages_fetched += 1
        time.sleep(REQUEST_DELAY_SECONDS)

        page_cardviews = page.get("cardviews", [])
        cardlist["cardviews"].extend(page_cardviews)

        lowest_num_decks = page_cardviews[-1].get("num_decks", 0) if page_cardviews else 0
        if lowest_num_decks < MIN_DECKS_FLOOR:
            break
        if page.get("is_paginated") and page.get("more"):
            cardlist["more"] = page["more"]

    cardlist.pop("is_paginated", None)
    cardlist["cardviews"] = [cv for cv in cardlist["cardviews"] if cv.get("num_decks", 0) >= MIN_DECKS_FLOOR]


def _paginate_page(payload: dict) -> None:
    """Follow pagination for every cardlist on a fetched page, in place."""
    cardlists = payload.get("container", {}).get("json_dict", {}).get("cardlists", [])
    for cardlist in cardlists:
        if cardlist.get("more"):
            _paginate_cardlist(cardlist)


def _fetch_page(kind: str, slug: str, force: bool, max_age_seconds: int) -> FetchResult:
    EDHREC_DIR.mkdir(parents=True, exist_ok=True)
    meta = _read_meta()
    cache_key = _cache_key(kind, slug)
    path = _page_path(kind, slug)

    if not force and _cache_is_fresh(cache_key, path, meta, max_age_seconds):
        return FetchResult(slug=slug, kind=kind, path=path, from_cache=True)

    url = _url_for(kind, slug)
    payload = _get_json(url, f"EDHREC {kind} page for {slug!r}")
    _paginate_page(payload)

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


def fetch_commander_detail_page(
    slug: str, force: bool = False, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS
) -> FetchResult:
    """Ensure the cached JSON detail page for one specific commander exists and is fresh.

    Unlike a color/theme list page, a detail page has no
    `container.json_dict.cardlists` to paginate -- `_paginate_page` (run
    by `_fetch_page` for every kind) already no-ops harmlessly on it,
    confirmed against the live shape (no `container` key at all).
    """
    return _fetch_page("commander", slug, force, max_age_seconds)


@dataclass
class FetchFailure:
    slug: str
    kind: str
    error: str


def fetch_all_pages(
    force: bool = False,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    color_slugs: list[str] | None = None,
    theme_slugs: list[str] | None = None,
) -> tuple[list[FetchResult], list[FetchFailure]]:
    """Fetch (or reuse cached) pages for every color-identity and theme slug.

    Color slugs are all verified real EDHREC pages, so a failure there
    is unexpected and worth surfacing loudly. Theme slugs in
    ``themes.py`` are still an unverified curated guess (see PLAN.md) —
    an individual bad theme slug shouldn't abort the whole run, so
    failures are collected and returned alongside the successes rather
    than raised.
    """
    results = []
    failures = []
    for slug in (all_slugs() if color_slugs is None else color_slugs):
        try:
            result = fetch_color_page(slug, force=force, max_age_seconds=max_age_seconds)
        except EdhrecFetchError as exc:
            failures.append(FetchFailure(slug=slug, kind="color", error=str(exc)))
            continue
        results.append(result)
        if not result.from_cache:
            time.sleep(REQUEST_DELAY_SECONDS)
    for slug in (THEME_SLUGS if theme_slugs is None else theme_slugs):
        try:
            result = fetch_theme_page(slug, force=force, max_age_seconds=max_age_seconds)
        except EdhrecFetchError as exc:
            failures.append(FetchFailure(slug=slug, kind="theme", error=str(exc)))
            continue
        results.append(result)
        if not result.from_cache:
            time.sleep(REQUEST_DELAY_SECONDS)
    return results, failures


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
