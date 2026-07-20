"""Build a filtered candidate pool of commanders for the picker.

Reads from ``data/commanders.db`` (built by ``db.py`` / `update-data`)
and narrows it down by color identity, deck-count range, and theme
tags into a bounded pool ready to hand to the Elo picker engine.
"""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass, field

DEFAULT_MAX_DECKS = 10_000
DEFAULT_MIN_DECKS = 100
DEFAULT_MIN_POOL_SIZE = 4
DEFAULT_MAX_POOL_SIZE = 40

# A widely-tagged commander can carry a dozen+ archetype tags, many of them
# marginal (a handful of decks each). Filtering/display only look at each
# commander's top few by deck count (see commander_themes.num_decks) so an
# obscure long tail doesn't dilute what the commander is actually known for.
TOP_THEMES_PER_COMMANDER = 3


class PoolTooSmallError(RuntimeError):
    pass


@dataclass
class Commander:
    name: str
    color_identity: str
    num_decks: int
    edhrec_url: str | None
    themes: tuple[str, ...]
    salt: float | None = None
    image_urls: list = field(default_factory=list)  # 2 entries for partner pairs / DFCs, else 0 or 1
    price: float | None = None  # from Scryfall's bulk data, see db.py's card_meta_lookup
    rank: int | None = None  # this commander's rank on the color/theme page it was found on
    mana_cost: str | None = None  # Scryfall shorthand, e.g. "{2}{B}{R}" -- from card_meta_lookup
    type_line: str | None = None  # from Scryfall's card_meta_lookup
    power_level: int | None = None  # dominant EDHREC Commander Bracket (1-5), from a cached detail page


@dataclass
class PoolFilters:
    colors: str | None = None  # e.g. "BRG" -- allowed colors; None = no color filter
    color_mode: str = "subset"  # "subset" (commander's colors must fit within `colors`) or "exact"
    max_decks: int | None = DEFAULT_MAX_DECKS
    min_decks: int | None = DEFAULT_MIN_DECKS
    themes: tuple[str, ...] = ()
    themes_mode: str = "any"  # "any" (OR) or "all" (AND)
    # Opt-in, unlike max_decks's always-on-but-generous default -- many
    # commanders (esp. Partner/Background pairs missing one half's
    # Scryfall match) have no price data at all, so a commander with
    # price=None is never excluded by this filter even when it's set
    # (see _filtered_candidates): "we don't know" is friendlier than
    # silently shrinking the pool over a data gap.
    max_price: float | None = None


def _color_identity_matches(color_identity: str, allowed: set[str], mode: str) -> bool:
    # Colorless commanders are stored as color_identity="" (no WUBRG
    # letters), but the UI represents "Colorless" as the pseudo-color
    # "C". Normalize so the two sides actually mean the same thing:
    # without this, `set("")` is the empty set, which is a subset of
    # *any* allowed set in "subset" mode -- colorless commanders would
    # leak into every color selection regardless of whether "C" was
    # actually picked, and would never match "C" itself in "exact"
    # mode since `set() != {"C"}`.
    ci = set(color_identity) if color_identity else {"C"}
    if mode == "exact":
        return ci == allowed
    return ci <= allowed


def _load_themes_by_commander(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Each commander's theme tags, capped to its own top TOP_THEMES_PER_COMMANDER
    by deck count -- both filtering (matching a selected theme) and display
    (Commander.themes) only ever see a commander's strongest few archetypes.
    """
    themes_by_commander: dict[str, set[str]] = {}
    rows = conn.execute(
        """
        SELECT commander_name, theme FROM (
            SELECT commander_name, theme,
                   ROW_NUMBER() OVER (
                       PARTITION BY commander_name ORDER BY num_decks DESC
                   ) AS rn
            FROM commander_themes
        )
        WHERE rn <= ?
        """,
        (TOP_THEMES_PER_COMMANDER,),
    )
    for row in rows:
        themes_by_commander.setdefault(row["commander_name"], set()).add(row["theme"])
    return themes_by_commander


def _filtered_candidates(conn: sqlite3.Connection, filters: PoolFilters) -> list[Commander]:
    """Every commander matching filters, with no pool-size bounding applied."""
    # None means "no color filter at all", regardless of color_mode --
    # this used to default to the full WUBRG set as a stand-in for "no
    # filter", which is harmless in "subset" mode (every identity is a
    # subset of all 5 colors) but was actively wrong in "exact" mode:
    # it silently meant "only 5-color commanders" instead of "no
    # filter", so leaving colors unset with "exact" selected returned a
    # near-empty result instead of everything.
    allowed_colors = set(filters.colors.upper()) if filters.colors else None
    wanted_themes = set(filters.themes)
    # Always loaded, not just when filtering by theme -- Commander.themes
    # is informational output regardless of whether themes were filtered on.
    themes_by_commander = _load_themes_by_commander(conn)

    candidates = []
    for row in conn.execute(
        "SELECT name, color_identity, num_decks, edhrec_url, salt, image_urls, price, rank, mana_cost, type_line, power_level "
        "FROM commanders"
    ):
        if allowed_colors is not None and not _color_identity_matches(
            row["color_identity"], allowed_colors, filters.color_mode
        ):
            continue
        if filters.max_decks is not None and row["num_decks"] > filters.max_decks:
            continue
        if filters.min_decks is not None and row["num_decks"] < filters.min_decks:
            continue
        # Permissive on missing data -- see PoolFilters.max_price's comment.
        if filters.max_price is not None and row["price"] is not None and row["price"] > filters.max_price:
            continue

        commander_themes = themes_by_commander.get(row["name"], set())
        if wanted_themes:
            matches = (
                wanted_themes <= commander_themes
                if filters.themes_mode == "all"
                else bool(wanted_themes & commander_themes)
            )
            if not matches:
                continue

        candidates.append(
            Commander(
                name=row["name"],
                color_identity=row["color_identity"],
                num_decks=row["num_decks"],
                edhrec_url=row["edhrec_url"],
                themes=tuple(sorted(commander_themes)),
                salt=row["salt"],
                image_urls=json.loads(row["image_urls"]) if row["image_urls"] else [],
                price=row["price"],
                rank=row["rank"],
                mana_cost=row["mana_cost"],
                type_line=row["type_line"],
                power_level=row["power_level"],
            )
        )
    return candidates


def list_known_themes(conn: sqlite3.Connection) -> list[str]:
    """Every distinct theme tag actually stored in commander_themes.

    Data-driven, unlike the curated `themes.py::THEME_SLUGS` list (which
    only drives which shallow tag pages get fetched) -- once commanders
    have real per-commander tags (see db.py's `_apply_commander_detail`),
    this reflects that richer, EDHREC-defined vocabulary directly.
    """
    rows = conn.execute("SELECT DISTINCT theme FROM commander_themes ORDER BY theme").fetchall()
    return [row["theme"] for row in rows]


def count_matches(conn: sqlite3.Connection, filters: PoolFilters) -> int:
    """Total commanders matching filters, before pool-size bounding.

    For UI live-preview use ("N commanders match your filters") --
    distinct from build_pool's returned list, which is capped to
    max_pool_size.
    """
    return len(_filtered_candidates(conn, filters))


def build_pool(
    conn: sqlite3.Connection,
    filters: PoolFilters,
    max_pool_size: int = DEFAULT_MAX_POOL_SIZE,
    min_pool_size: int = DEFAULT_MIN_POOL_SIZE,
    rng: random.Random | None = None,
) -> list[Commander]:
    """Filter commanders.db down to a bounded candidate pool.

    Raises PoolTooSmallError if the filtered set (before size capping)
    has fewer than min_pool_size candidates -- callers should loosen
    filters rather than hand the picker an unusably small pool.

    When the filtered set exceeds max_pool_size, a random sample is
    taken rather than always truncating to the most-built candidates
    -- the whole point is variety across the "under 10k" range, not
    always showing the same highest-deck-count commanders within it.
    """
    candidates = _filtered_candidates(conn, filters)

    if len(candidates) < min_pool_size:
        raise PoolTooSmallError(
            f"Only {len(candidates)} commander(s) match these filters "
            f"(need at least {min_pool_size}). Try loosening colors/deck-count/themes."
        )

    if len(candidates) > max_pool_size:
        rng = rng or random.Random()
        candidates = rng.sample(candidates, max_pool_size)

    return candidates


class CommanderLookupError(RuntimeError):
    pass


def search_commanders(conn: sqlite3.Connection, query: str, limit: int = 20):
    """Lightweight name search for the custom-list autocomplete.

    Returns raw rows (name, color_identity, num_decks) rather than full
    Commander objects -- the dropdown only needs enough to tell
    similarly-named commanders apart, not themes/images/price.
    """
    like = f"%{query}%"
    return conn.execute(
        "SELECT name, color_identity, num_decks FROM commanders "
        "WHERE name LIKE ? ORDER BY num_decks DESC LIMIT ?",
        (like, limit),
    ).fetchall()


def commander_images_by_name(conn: sqlite3.Connection, names: list[str]) -> dict[str, dict]:
    """Bulk lookup of image_urls/color_identity by exact commander name.

    For enriching a list of names sourced from elsewhere (e.g. the
    32-deck challenge tracker's candidate shortlist, which only stores
    names) with card art -- not full Commander objects, just enough to
    render a thumbnail + pips. A name with no catalog match (deleted
    from EDHREC, a typo, a card not in this catalog's colors/themes
    scope) is simply omitted -- callers should treat a missing entry as
    "no art available," not an error.
    """
    if not names:
        return {}
    placeholders = ",".join("?" * len(names))
    rows = conn.execute(
        f"SELECT name, image_urls, color_identity FROM commanders WHERE name IN ({placeholders})",
        names,
    ).fetchall()
    return {
        row["name"]: {
            "image_urls": json.loads(row["image_urls"]) if row["image_urls"] else [],
            "color_identity": row["color_identity"],
        }
        for row in rows
    }


def commanders_by_names(conn: sqlite3.Connection, names: list[str]) -> list[Commander]:
    """Exact-name lookup for custom lists -- bypasses filtering entirely.

    Preserves the caller's order (the order the user added them) and
    raises CommanderLookupError on any unknown name or duplicate, rather
    than silently deduping/dropping -- a session should either match
    exactly what the user built, or fail clearly.
    """
    seen = set()
    duplicates = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    if duplicates:
        raise CommanderLookupError(f"Duplicate commander name(s): {', '.join(sorted(duplicates))}")

    themes_by_commander = _load_themes_by_commander(conn)
    rows_by_name = {
        row["name"]: row
        for row in conn.execute(
            "SELECT name, color_identity, num_decks, edhrec_url, salt, image_urls, price, rank, mana_cost, type_line, power_level "
            "FROM commanders"
        )
    }

    candidates = []
    missing = []
    for name in names:
        row = rows_by_name.get(name)
        if row is None:
            missing.append(name)
            continue
        candidates.append(
            Commander(
                name=row["name"],
                color_identity=row["color_identity"],
                num_decks=row["num_decks"],
                edhrec_url=row["edhrec_url"],
                themes=tuple(sorted(themes_by_commander.get(row["name"], set()))),
                salt=row["salt"],
                image_urls=json.loads(row["image_urls"]) if row["image_urls"] else [],
                price=row["price"],
                rank=row["rank"],
                mana_cost=row["mana_cost"],
                type_line=row["type_line"],
                power_level=row["power_level"],
            )
        )
    if missing:
        raise CommanderLookupError(f"Unknown commander name(s): {', '.join(missing)}")
    return candidates


def describe_filters(filters: PoolFilters) -> str:
    """Human-readable summary of a PoolFilters, used as a session's stored description."""
    parts = []
    if filters.colors:
        parts.append(f"colors={filters.colors} ({filters.color_mode})")
    if filters.max_decks is not None:
        parts.append(f"max_decks={filters.max_decks}")
    if filters.min_decks is not None:
        parts.append(f"min_decks={filters.min_decks}")
    if filters.themes:
        parts.append(f"themes={','.join(filters.themes)} ({filters.themes_mode})")
    return " ".join(parts) or "no filters"
