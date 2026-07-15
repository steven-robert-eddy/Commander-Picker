"""EDHREC archetype/theme page slugs.

Best-effort list of theme slugs EDHREC uses for pages like
``https://json.edhrec.com/pages/themes/tokens.json``. UNVERIFIED against
a live response (see PLAN.md "known gaps" and ``edhrec_client.py``) —
these are the archetype names commonly seen linked from EDHREC's site
navigation. Add/remove/rename entries here once confirmed; nothing else
needs to change since ``db.py`` just iterates this list.
"""

from __future__ import annotations

THEME_SLUGS = [
    "tokens",
    "plus-1-plus-1-counters",
    "aristocrats",
    "voltron",
    "group-hug",
    "reanimator",
    "stax",
    "lifegain",
    "spellslinger",
    "artifacts",
    "enchantress",
    "landfall",
    "blink",
    "mill",
    "storm",
    "control",
    "aggro",
    "ramp",
]
