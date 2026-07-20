"""EDHREC archetype/theme page slugs.

List of theme slugs EDHREC uses for pages like
``https://json.edhrec.com/pages/tags/tokens.json`` (EDHREC calls these
"tags" internally; see ``edhrec_client.py``'s module docstring for the
URL template). **Verified 2026-07-20** by fetching every slug below
live against ``json.edhrec.com`` and confirming a real cardlist comes
back, and cross-checked against EDHREC's own tag index
(``https://json.edhrec.com/pages/tags.json``, a "Tags By Popularity"
page listing ~400 tags total). This is a curated subset of that index:
genuine deck-building archetypes/strategies (tokens, aristocrats,
voltron, ...), deliberately excluding creature-type tribal tags
(elves, zombies, ...) and narrow single-keyword mechanic tags (cycling,
morph, ninjutsu, ...) to keep the list focused. Add/remove/rename
entries here once confirmed; nothing else needs to change since
``db.py`` just iterates this list.
"""

from __future__ import annotations

THEME_SLUGS = [
    "aggro",
    "aristocrats",
    "artifacts",
    "auras",
    "big-mana",
    "blink",
    "burn",
    "combo",
    "control",
    "discard",
    "enchantress",
    "equipment",
    "extra-combats",
    "extra-turns",
    "forced-combat",
    "good-stuff",
    "graveyard",
    "group-hug",
    "group-slug",
    "hatebears",
    "landfall",
    "lifegain",
    "midrange",
    "mill",
    "monarch",
    "pillow-fort",
    "plus-1-plus-1-counters",
    "ramp",
    "reanimator",
    "sacrifice",
    "self-mill",
    "spellslinger",
    "stax",
    "storm",
    "tempo",
    "theft",
    "tokens",
    "toolbox",
    "topdeck",
    "treasure",
    "voltron",
    "wheels",
]
