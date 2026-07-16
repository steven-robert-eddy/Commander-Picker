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

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from commander_picker import edhrec_client
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
    salt: float | None = None  # not populated in Phase 1 — see "Known gap" below
    image_url: str | None = None  # not populated in Phase 1 — see PLAN.md Phase 5
    price: float | None = None  # not populated in Phase 1 — see PLAN.md Phase 5


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
    )


def _available_slugs(kind: str, requested: list[str]) -> list[str]:
    return [slug for slug in requested if edhrec_client.page_exists(kind, slug)]


def load_commanders(
    color_slugs: list[str] | None = None,
    theme_slugs: list[str] | None = None,
) -> dict[str, CommanderRecord]:
    """Build the merged commander dict from whatever cached pages exist.

    Color pages are authoritative for identity/deck-count fields; theme
    pages only contribute theme tags for commanders already found on a
    color page (a commander missing its color page is skipped with no
    error, since Phase 1's contract is "load what's cached").
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

    return commanders


def build_database(
    color_slugs: list[str] | None = None,
    theme_slugs: list[str] | None = None,
    db_path: Path = DB_PATH,
) -> Path:
    """Load cached pages and (re)write `data/commanders.db`."""
    commanders = load_commanders(color_slugs=color_slugs, theme_slugs=theme_slugs)

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
                image_url TEXT,
                price REAL
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
                    (name, sanitized, color_identity, num_decks, salt, edhrec_url, image_url, price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.name,
                    record.sanitized,
                    "".join(record.color_identity),
                    record.num_decks,
                    record.salt,
                    record.edhrec_url,
                    record.image_url,
                    record.price,
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


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    if not db_path.exists():
        raise DbError(f"{db_path} does not exist yet. Run `commander-picker update-data` first.")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
