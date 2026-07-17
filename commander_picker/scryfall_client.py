"""Fetch and cache Scryfall's oracle_cards bulk data, for card art lookups.

Scryfall's bulk-data API (https://scryfall.com/docs/api/bulk-data) is
well-documented and stable, but -- like edhrec_client.py -- this dev
sandbox's egress policy blocks api.scryfall.com directly (confirmed
403 via the proxy), so the exact response shape below is built from
public documentation, not a captured live response. Same discipline as
edhrec_client.py applies: verify against a live `update-data` run once
reachable and fix up if it differs.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

BULK_DATA_INDEX_URL = "https://api.scryfall.com/bulk-data"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SCRYFALL_DIR = DATA_DIR / "scryfall"
ORACLE_CARDS_PATH = SCRYFALL_DIR / "oracle_cards.json"
META_PATH = SCRYFALL_DIR / "meta.json"

# Scryfall's own bulk data updates roughly daily.
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60

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

    download_uri = oracle_entry.get("download_uri")
    if not download_uri:
        raise ScryfallFetchError("Scryfall's oracle_cards bulk-data entry has no download_uri")

    try:
        cards_resp = requests.get(download_uri, headers=REQUEST_HEADERS, timeout=180)
        cards_resp.raise_for_status()
    except requests.RequestException as exc:
        raise ScryfallFetchError(f"Failed to download Scryfall oracle_cards bulk file: {exc}") from exc

    ORACLE_CARDS_PATH.write_bytes(cards_resp.content)
    _write_meta({"fetched_at": time.time(), "download_uri": download_uri})
    return ORACLE_CARDS_PATH


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
        urls = _card_face_image_urls(card)
        if urls and card.get("name"):
            lookup[card["name"]] = urls
    return lookup


def resolve_image_urls(commander_name: str, lookup: dict[str, list[str]]) -> list[str]:
    """Look up a commander's image(s), handling EDHREC's Partner-pair naming.

    EDHREC displays two-Partner (or Background) commanders as "A // B",
    but that combined string usually isn't a real Scryfall card name --
    Scryfall has "A" and "B" as two separate cards. In that case, look
    each half up independently and show both. True double-faced/transform
    cards already use "A // B" as their actual single Scryfall card name
    too (with front/back already folded into one lookup entry by
    `build_image_lookup`), so those match directly without needing the
    per-half fallback.
    """
    if commander_name in lookup:
        return lookup[commander_name]
    if " // " in commander_name:
        first_half, second_half = commander_name.split(" // ", 1)
        return lookup.get(first_half, []) + lookup.get(second_half, [])
    return []
