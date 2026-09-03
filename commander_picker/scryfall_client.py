"""Fetch and cache Scryfall's oracle_cards bulk data, for card art lookups.

As of August 2026, Scryfall's bulk-data index (https://scryfall.com/docs/api/bulk-data)
no longer returns a plain-JSON `download_uri` for oracle_cards -- only a
gzip-compressed JSON Lines `jsonl_download_uri`, one card object per line
instead of a single JSON array. `fetch_oracle_cards` decompresses/reassembles
that into a JSON array on disk so `ORACLE_CARDS_PATH` and every reader's
`json.load` stay unchanged; the old plain-JSON `download_uri` is still
accepted as a fallback in case Scryfall reintroduces it.
"""

from __future__ import annotations

import gzip
import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

BULK_DATA_INDEX_URL = "https://api.scryfall.com/bulk-data"
SETS_INDEX_URL = "https://api.scryfall.com/sets"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SCRYFALL_DIR = DATA_DIR / "scryfall"
ORACLE_CARDS_PATH = SCRYFALL_DIR / "oracle_cards.json"
SETS_PATH = SCRYFALL_DIR / "sets.json"
META_PATH = SCRYFALL_DIR / "meta.json"
SETS_META_PATH = SCRYFALL_DIR / "sets_meta.json"

# Scryfall's own bulk data updates roughly daily.
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60

# set_type values that can plausibly print Commander-legal cards --
# excludes things like token, art_series, memorabilia, minigame, etc.
# Used to trim the EDHREC set-page discovery crawl (see edhrec_client.py's
# discover_set_slugs) down from every Scryfall set ever printed to a
# reasonable candidate list.
RELEVANT_SET_TYPES = {
    "expansion",
    "core",
    "commander",
    "masters",
    "draft_innovation",
}

# Non-game objects Scryfall includes in the same oracle_cards bulk
# file, sharing display names with real cards they depict/reference
# (e.g. an Art Series card named identically to the real card's art) --
# excluded so a same-named collectible can't silently overwrite the
# real card's image/meta lookup entry.
_NON_GAME_LAYOUTS = {"art_series", "token", "double_faced_token", "emblem", "scheme", "vanguard", "planar"}


def _is_game_card(card: dict) -> bool:
    return card.get("layout") not in _NON_GAME_LAYOUTS

USER_AGENT = "commander-picker/0.1 (+https://github.com/steven-robert-eddy/commander-picker)"
REQUEST_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json;q=0.9,*/*;q=0.8"}


class ScryfallFetchError(RuntimeError):
    pass


def _read_meta() -> dict:
    if not META_PATH.exists():
        return {}
    try:
        return json.loads(META_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_meta(meta: dict) -> None:
    META_PATH.write_text(json.dumps(meta, indent=2))


def _cache_is_fresh(max_age_seconds: int) -> bool:
    if not ORACLE_CARDS_PATH.exists():
        return False
    fetched_at = _read_meta().get("fetched_at")
    if fetched_at is None:
        return False
    return (time.time() - fetched_at) < max_age_seconds


def fetch_oracle_cards(force: bool = False, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS) -> Path:
    """Ensure data/scryfall/oracle_cards.json exists and is fresh; return its path.

    Two requests: GET the bulk-data index to find the current
    oracle_cards download URL (these rotate), then GET that URL for
    the actual (large, ~couple hundred MB) card data file.
    """
    SCRYFALL_DIR.mkdir(parents=True, exist_ok=True)

    if not force and _cache_is_fresh(max_age_seconds):
        return ORACLE_CARDS_PATH

    try:
        index_resp = requests.get(BULK_DATA_INDEX_URL, headers=REQUEST_HEADERS, timeout=30)
        index_resp.raise_for_status()
        index = index_resp.json()
    except requests.RequestException as exc:
        raise ScryfallFetchError(f"Failed to fetch Scryfall bulk-data index: {exc}") from exc

    oracle_entry = next((d for d in index.get("data", []) if d.get("type") == "oracle_cards"), None)
    if oracle_entry is None:
        raise ScryfallFetchError("No 'oracle_cards' entry in Scryfall's bulk-data index")

    # jsonl_download_uri is what Scryfall actually serves now; download_uri
    # is kept as a fallback for the old plain-JSON shape (see module
    # docstring, and the tests exercising both).
    download_uri = oracle_entry.get("jsonl_download_uri") or oracle_entry.get("download_uri")
    if not download_uri:
        raise ScryfallFetchError("Scryfall's oracle_cards bulk-data entry has no download URI")

    try:
        cards_resp = requests.get(download_uri, headers=REQUEST_HEADERS, timeout=180)
        cards_resp.raise_for_status()
    except requests.RequestException as exc:
        raise ScryfallFetchError(f"Failed to download Scryfall oracle_cards bulk file: {exc}") from exc

    raw = cards_resp.content
    if download_uri.endswith(".gz"):
        raw = gzip.decompress(raw)
    if download_uri.endswith((".jsonl", ".jsonl.gz")):
        # One JSON object per line -- reassemble into the single JSON array
        # every reader of ORACLE_CARDS_PATH (build_image_lookup etc.) expects.
        cards = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        ORACLE_CARDS_PATH.write_text(json.dumps(cards))
    else:
        ORACLE_CARDS_PATH.write_bytes(raw)
    _write_meta({"fetched_at": time.time(), "download_uri": download_uri})
    return ORACLE_CARDS_PATH


def _sets_cache_is_fresh(max_age_seconds: int) -> bool:
    if not SETS_PATH.exists():
        return False
    if not SETS_META_PATH.exists():
        return False
    try:
        meta = json.loads(SETS_META_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    fetched_at = meta.get("fetched_at")
    if fetched_at is None:
        return False
    return (time.time() - fetched_at) < max_age_seconds


def fetch_set_index(force: bool = False, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS) -> list[dict]:
    """Fetch (or reuse cached) Scryfall's set index and return the relevant subset.

    Unlike `fetch_oracle_cards`, this is a single small (~1MB) request --
    Scryfall's `/sets` endpoint, not the giant per-card bulk-data file --
    so it's cheap enough to call before any EDHREC set-page discovery
    crawl. Returns only entries whose `set_type` is in
    `RELEVANT_SET_TYPES`, each a `{code, name, set_type, released_at}`
    dict.
    """
    SCRYFALL_DIR.mkdir(parents=True, exist_ok=True)

    if not force and _sets_cache_is_fresh(max_age_seconds):
        payload = json.loads(SETS_PATH.read_text())
    else:
        try:
            resp = requests.get(SETS_INDEX_URL, headers=REQUEST_HEADERS, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise ScryfallFetchError(f"Failed to fetch Scryfall set index: {exc}") from exc
        SETS_PATH.write_text(json.dumps(payload))
        SETS_META_PATH.write_text(json.dumps({"fetched_at": time.time()}))

    return [
        {
            "code": entry["code"],
            "name": entry.get("name"),
            "set_type": entry.get("set_type"),
            "released_at": entry.get("released_at"),
        }
        for entry in payload.get("data", [])
        if entry.get("set_type") in RELEVANT_SET_TYPES and entry.get("code")
    ]


def _one_face_image_url(image_uris: dict | None) -> str | None:
    if not image_uris:
        return None
    return image_uris.get("normal") or image_uris.get("large") or image_uris.get("art_crop")


def _card_face_image_urls(card: dict) -> list[str]:
    """The image(s) that make up this card, in display order.

    Most cards have a single `image_uris` and this returns one URL.
    Double-faced/transform/modal-DFC cards carry per-face `image_uris`
    instead (front and back are genuinely different images) -- for
    those, return one URL per face so both sides can be shown. Layouts
    like split or adventure have multiple `card_faces` entries too, but
    share a single whole-card `image_uris` at the top level rather than
    per-face images, so those still collapse to one URL.
    """
    image_uris = card.get("image_uris")
    if image_uris is not None:
        url = _one_face_image_url(image_uris)
        return [url] if url else []

    urls = []
    for face in card.get("card_faces") or []:
        url = _one_face_image_url(face.get("image_uris"))
        if url:
            urls.append(url)
    return urls


def build_image_lookup(oracle_cards_path: Path = ORACLE_CARDS_PATH) -> dict[str, list[str]]:
    """Card name -> ordered list of image URLs, for every card that has any.

    Usually a single-element list; two elements for double-faced/transform
    cards (front + back), so both sides can be displayed.
    """
    if not oracle_cards_path.exists():
        raise ScryfallFetchError(
            f"{oracle_cards_path} does not exist yet. Run `commander-picker update-data` first."
        )
    with open(oracle_cards_path, "r", encoding="utf-8") as fh:
        cards = json.load(fh)

    lookup: dict[str, list[str]] = {}
    for card in cards:
        if not _is_game_card(card):
            continue
        urls = _card_face_image_urls(card)
        if urls and card.get("name"):
            lookup[card["name"]] = urls

    # EDHREC names true double-faced/transform/MDFC commanders after their
    # front face only (e.g. "Heliod, the Radiant Dawn", not "Heliod, the
    # Radiant Dawn // Heliod, the Warped Eclipse") -- add a front-face-name
    # alias for those so resolve_image_urls's exact-match path still finds
    # them. `setdefault` so this never overrides a real card's own full name.
    for card in cards:
        if not _is_game_card(card):
            continue
        faces = card.get("card_faces") or []
        if len(faces) >= 2 and card.get("name") in lookup:
            front_name = faces[0].get("name")
            if front_name:
                lookup.setdefault(front_name, lookup[card["name"]])
    return lookup


def resolve_image_urls(commander_name: str, lookup: dict[str, list[str]]) -> list[str]:
    """Look up a commander's image(s), handling EDHREC's Partner-pair naming.

    EDHREC displays two-Partner (or Background) commanders as "A // B",
    but that combined string usually isn't a real Scryfall card name --
    Scryfall has "A" and "B" as two separate cards. In that case, look
    each half up independently and show both. True double-faced/transform
    cards' full "A // B" Scryfall name, and EDHREC's front-face-only name
    for the same card, both resolve directly via `lookup` (the latter via
    the front-face alias `build_image_lookup` adds), so those match
    without needing the per-half fallback.
    """
    if commander_name in lookup:
        return lookup[commander_name]
    if " // " in commander_name:
        first_half, second_half = commander_name.split(" // ", 1)
        return lookup.get(first_half, []) + lookup.get(second_half, [])
    return []


@dataclass
class CardMeta:
    mana_cost: str | None = None
    type_line: str | None = None
    price_usd: float | None = None
    # Rules text -- used by guess_game.py to build its line-by-line
    # reveal clues. Same front-face fallback as mana_cost/type_line: a
    # transform/MDFC card's real text lives on its front face, not the
    # often-blank top-level field.
    oracle_text: str | None = None


def _card_meta(card: dict) -> CardMeta:
    faces = card.get("card_faces") or []
    # Transform/modal-DFC cards carry their real cost/type on the front
    # face rather than the top level (which is often blank for these) --
    # same asymmetry _card_face_image_urls already works around for art.
    mana_cost = card.get("mana_cost") or (faces[0].get("mana_cost") if faces else None)
    type_line = card.get("type_line") or (faces[0].get("type_line") if faces else None)
    oracle_text = card.get("oracle_text") or (faces[0].get("oracle_text") if faces else None)
    prices = card.get("prices") or {}
    raw_price = prices.get("usd") or prices.get("usd_foil")
    price_usd = float(raw_price) if raw_price else None
    return CardMeta(
        mana_cost=mana_cost or None,
        type_line=type_line or None,
        price_usd=price_usd,
        oracle_text=oracle_text or None,
    )


def build_card_meta_lookup(oracle_cards_path: Path = ORACLE_CARDS_PATH) -> dict[str, CardMeta]:
    """Card name -> CardMeta (mana cost, type line, USD price), for every card.

    A separate pass over the same bulk file build_image_lookup already
    parses -- kept independent rather than merged into one function so
    neither one's tests/call sites need to change shape. The Scryfall
    bulk download is the real bottleneck (per the README), not one extra
    in-memory iteration over an already-loaded list.
    """
    if not oracle_cards_path.exists():
        raise ScryfallFetchError(
            f"{oracle_cards_path} does not exist yet. Run `commander-picker update-data` first."
        )
    with open(oracle_cards_path, "r", encoding="utf-8") as fh:
        cards = json.load(fh)

    lookup: dict[str, CardMeta] = {}
    for card in cards:
        if not _is_game_card(card):
            continue
        if card.get("name"):
            lookup[card["name"]] = _card_meta(card)

    # Same front-face alias as build_image_lookup, for the same reason:
    # EDHREC names transform commanders after their front face only.
    for card in cards:
        if not _is_game_card(card):
            continue
        faces = card.get("card_faces") or []
        if len(faces) >= 2 and card.get("name") in lookup:
            front_name = faces[0].get("name")
            if front_name:
                lookup.setdefault(front_name, lookup[card["name"]])
    return lookup


def resolve_card_meta(commander_name: str, lookup: dict[str, CardMeta]) -> CardMeta:
    """Look up a commander's card details, handling EDHREC's Partner-pair naming.

    Mirrors resolve_image_urls's Partner-pair split: an "A // B" pair
    that isn't a single Scryfall card gets both halves' mana cost/type
    line concatenated (" // ", matching Scryfall's own DFC convention)
    and their prices summed (a deck needs both cards) -- only when both
    halves have a price; otherwise None rather than an understated total.
    """
    if commander_name in lookup:
        return lookup[commander_name]
    if " // " in commander_name:
        first_half, second_half = commander_name.split(" // ", 1)
        a = lookup.get(first_half)
        b = lookup.get(second_half)
        if a is None and b is None:
            return CardMeta()
        a = a or CardMeta()
        b = b or CardMeta()
        mana_cost = " // ".join(m for m in (a.mana_cost, b.mana_cost) if m) or None
        type_line = " // ".join(t for t in (a.type_line, b.type_line) if t) or None
        oracle_text = "\n".join(t for t in (a.oracle_text, b.oracle_text) if t) or None
        price_usd = a.price_usd + b.price_usd if a.price_usd is not None and b.price_usd is not None else None
        return CardMeta(mana_cost=mana_cost, type_line=type_line, price_usd=price_usd, oracle_text=oracle_text)
    return CardMeta()
