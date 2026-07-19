"""Load cached EDHREC pages into a queryable SQLite database.

Reads whatever color-identity and theme pages are present in
``data/edhrec/`` (via ``edhrec_client.load_page``) and builds
``data/commanders.db``: one row per commander, plus a junction table
recording which theme pages each commander appeared on.

The EDHREC JSON parsing (``_cardviews_from_page``,
``_cardview_to_record``) is isolated in small functions here
specifically so that verifying/fixing the real response shape against
live edhrec.com is a local change — the rest of the pipeline (caching,
SQLite schema, CLI) doesn't need to move. Color-identity pages are
verified as of 2026-07-16 (see ``_cardview_to_record``'s docstring);
theme pages are still unverified — the URL template 403s against real
EDHREC and needs the correct pattern confirmed.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from commander_picker import edhrec_client, scryfall_client
from commander_picker.colors import COLOR_IDENTITY_BY_SLUG, all_slugs
from commander_picker.themes import THEME_SLUGS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "commanders.db"


class DbError(RuntimeError):
    pass


@dataclass
class CommanderRecord:
    name: str
    sanitized: str
    color_identity: tuple  # e.g. ("B", "R")
    num_decks: int
    edhrec_url: str | None
    themes: set = field(default_factory=set)
    salt: float | None = None  # never populated -- not on EDHREC's color/theme list endpoints
    image_urls: list = field(default_factory=list)  # 2 entries for partner pairs / DFCs, else 0 or 1
    price: float | None = None  # populated from Scryfall's bulk data, see build_database's card_meta_lookup
    rank: int | None = None  # this commander's rank within the page it was found on
    mana_cost: str | None = None  # populated from Scryfall's bulk data, see build_database's card_meta_lookup
    type_line: str | None = None  # populated from Scryfall's bulk data, see build_database's card_meta_lookup


def _cardviews_from_page(page_json: dict) -> list[dict]:
    cardlists = page_json.get("container", {}).get("json_dict", {}).get("cardlists", [])
    views = []
    for cardlist in cardlists:
        views.extend(cardlist.get("cardviews", []))
    return views


def _cardview_to_record(cardview: dict, color_identity: tuple) -> CommanderRecord:
    """Build a record from one cardview entry on a color-identity page.

    Verified 2026-07-16 against a live ``.../pages/commanders/rakdos.json``
    response: cardviews carry ``name``/``sanitized``/``num_decks``/``url``
    but no per-card ``colors`` or ``salt`` field — color identity comes
    from the page itself (every card on the ``rakdos`` page has BR
    identity), and salt isn't available on this list endpoint at all
    (known gap — would need a per-commander detail page, deferred).
    """
    url = cardview.get("url")
    return CommanderRecord(
        name=cardview["name"],
        sanitized=cardview.get("sanitized", ""),
        color_identity=color_identity,
        num_decks=cardview.get("num_decks", 0),
        edhrec_url=f"https://edhrec.com{url}" if url else None,
        rank=cardview.get("rank"),
    )


# Keep only the highest-count tags per commander -- a popular commander
# can have 50-100+ EDHREC taglinks, many down to count:1 (noise). Top-N
# by count is signal, not the full tail.
TOP_TAGS_PER_COMMANDER = 10


def _available_slugs(kind: str, requested: list[str]) -> list[str]:
    return [slug for slug in requested if edhrec_client.page_exists(kind, slug)]


def _apply_commander_detail(record: CommanderRecord, payload: dict) -> None:
    """Merge salt + top taglinks-derived themes from a cached per-commander
    detail page into an already-built CommanderRecord.

    Verified 2026-07-19 against a live
    ``.../pages/commanders/rakdos-lord-of-riots.json`` response: unlike a
    color/theme list page, a detail page is flat at the top level (no
    ``container`` wrapper) -- salt lives at ``card.salt``, and deck-count-
    weighted tags at ``panels.taglinks`` (each a
    ``{"count", "slug", "value"}`` dict).
    """
    card = payload.get("card", {})
    record.salt = card.get("salt")

    taglinks = payload.get("panels", {}).get("taglinks", [])
    top_tags = sorted(taglinks, key=lambda t: t.get("count", 0), reverse=True)[:TOP_TAGS_PER_COMMANDER]
    record.themes.update(t["slug"] for t in top_tags if t.get("slug"))


def load_commanders(
    color_slugs: list[str] | None = None,
    theme_slugs: list[str] | None = None,
) -> dict[str, CommanderRecord]:
    """Build the merged commander dict from whatever cached pages exist.

    Color pages are authoritative for identity/deck-count fields; theme
    pages only contribute theme tags for commanders already found on a
    color page (a commander missing its color page is skipped with no
    error -- the contract here is "load what's cached"). A commander's
    own detail page (fetched separately via
    ``commander-picker enrich-commanders``, cached under EDHREC's
    "commander" kind) is applied last, if cached, adding its salt score
    and its own richer, deck-count-weighted tags -- a commander with no
    cached detail page yet is left exactly as before (``salt=None``,
    tag-page-only themes), same "load what's cached" contract.
    """
    color_slugs = _available_slugs("color", all_slugs() if color_slugs is None else color_slugs)
    theme_slugs = _available_slugs("theme", THEME_SLUGS if theme_slugs is None else theme_slugs)

    if not color_slugs:
        raise DbError(
            "No cached EDHREC color pages found. Run `commander-picker update-data` first."
        )

    commanders: dict[str, CommanderRecord] = {}
    for slug in color_slugs:
        color_identity = COLOR_IDENTITY_BY_SLUG.get(slug, ())
        page = edhrec_client.load_page("color", slug)
        for cardview in _cardviews_from_page(page):
            record = _cardview_to_record(cardview, color_identity)
            commanders[record.name] = record

    for slug in theme_slugs:
        page = edhrec_client.load_page("theme", slug)
        for cardview in _cardviews_from_page(page):
            name = cardview.get("name")
            if name in commanders:
                commanders[name].themes.add(slug)

    for record in commanders.values():
        if edhrec_client.page_exists("commander", record.sanitized):
            payload = edhrec_client.load_page("commander", record.sanitized)
            _apply_commander_detail(record, payload)

    return commanders


def build_database(
    color_slugs: list[str] | None = None,
    theme_slugs: list[str] | None = None,
    db_path: Path = DB_PATH,
    image_lookup: dict[str, list[str]] | None = None,
    card_meta_lookup: dict[str, "scryfall_client.CardMeta"] | None = None,
) -> Path:
    """Load cached pages and (re)write `data/commanders.db`.

    ``image_lookup`` is a card name -> image URLs dict (from
    ``scryfall_client.build_image_lookup``); when given, each
    commander's ``image_urls`` is resolved from it (handling EDHREC's
    Partner-pair naming, and double-faced/transform cards' two sides,
    via ``scryfall_client.resolve_image_urls``). Omitted entirely
    (``None``) if the caller skipped fetching images — left as ``[]``
    in that case, same as before this existed.

    ``card_meta_lookup`` is a card name -> CardMeta dict (from
    ``scryfall_client.build_card_meta_lookup``); when given, each
    commander's ``mana_cost``/``type_line``/``price`` are resolved from
    it the same way, via ``scryfall_client.resolve_card_meta``. Kept as a
    separate optional param from ``image_lookup`` (not folded into one
    lookup) so a caller can supply either independently.
    """
    commanders = load_commanders(color_slugs=color_slugs, theme_slugs=theme_slugs)

    if image_lookup is not None:
        for record in commanders.values():
            record.image_urls = scryfall_client.resolve_image_urls(record.name, image_lookup)

    if card_meta_lookup is not None:
        for record in commanders.values():
            meta = scryfall_client.resolve_card_meta(record.name, card_meta_lookup)
            record.mana_cost = meta.mana_cost
            record.type_line = meta.type_line
            record.price = meta.price_usd

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE commanders (
                name TEXT PRIMARY KEY,
                sanitized TEXT,
                color_identity TEXT NOT NULL,
                num_decks INTEGER NOT NULL,
                salt REAL,
                edhrec_url TEXT,
                image_urls TEXT NOT NULL DEFAULT '[]',
                price REAL,
                rank INTEGER,
                mana_cost TEXT,
                type_line TEXT
            );
            CREATE TABLE commander_themes (
                commander_name TEXT NOT NULL REFERENCES commanders(name),
                theme TEXT NOT NULL,
                PRIMARY KEY (commander_name, theme)
            );
            CREATE INDEX idx_commanders_color_identity ON commanders(color_identity);
            CREATE INDEX idx_commanders_num_decks ON commanders(num_decks);
            CREATE INDEX idx_commander_themes_theme ON commander_themes(theme);
            """
        )

        for record in commanders.values():
            conn.execute(
                """
                INSERT INTO commanders
                    (name, sanitized, color_identity, num_decks, salt, edhrec_url, image_urls, price, rank, mana_cost, type_line)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.name,
                    record.sanitized,
                    "".join(record.color_identity),
                    record.num_decks,
                    record.salt,
                    record.edhrec_url,
                    json.dumps(record.image_urls),
                    record.price,
                    record.rank,
                    record.mana_cost,
                    record.type_line,
                ),
            )
            conn.executemany(
                "INSERT INTO commander_themes (commander_name, theme) VALUES (?, ?)",
                [(record.name, theme) for theme in sorted(record.themes)],
            )
        conn.commit()
    finally:
        conn.close()

    return db_path


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    # `db_path`'s default can't just be `= DB_PATH` -- that binds the
    # value at function-definition time, so monkeypatching the module
    # attribute later (as tests do) would silently have no effect on
    # calls that don't pass db_path explicitly.
    if db_path is None:
        db_path = DB_PATH
    if not db_path.exists():
        raise DbError(f"{db_path} does not exist yet. Run `commander-picker update-data` first.")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
