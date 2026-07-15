"""Color identity <-> EDHREC URL slug mapping.

EDHREC groups its commander/theme pages by color identity using slugs
like ``rakdos`` or ``mono-red`` in URLs such as
``https://json.edhrec.com/pages/commanders/rakdos.json``.

Confidence levels, since this environment currently has no network
access to edhrec.com to verify live (see PLAN.md "known gaps"):

- Colorless and mono-color slugs: high confidence, these are standard
  and simple (``colorless``, ``mono-white``, ...).
- Two-color (guild) and three-color (shard/wedge) slugs: high
  confidence — these reuse official Magic terminology (guild names like
  ``rakdos``, shard/wedge names like ``jund``) that EDHREC has used
  for years, not something EDHREC invented.
- Four- and five-color slugs: LOWER confidence. Best guess is the
  literal color letters concatenated in WUBRG order and lowercased
  (e.g. ``wubr``, ``wubrg``) since these combos don't have widely used
  nicknames. Verify against a live page once reachable.
"""

from __future__ import annotations

WUBRG = "WUBRG"


def _sort_colors(colors: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(colors, key=WUBRG.index))


# Two-color guild names.
_GUILDS = {
    ("W", "U"): "azorius",
    ("U", "B"): "dimir",
    ("B", "R"): "rakdos",
    ("R", "G"): "gruul",
    ("G", "W"): "selesnya",
    ("W", "B"): "orzhov",
    ("U", "R"): "izzet",
    ("B", "G"): "golgari",
    ("R", "W"): "boros",
    ("G", "U"): "simic",
}

# Three-color shard (Alara) and wedge (Khans) names.
_TRICOLOR = {
    ("W", "U", "B"): "esper",
    ("U", "B", "R"): "grixis",
    ("B", "R", "G"): "jund",
    ("R", "G", "W"): "naya",
    ("G", "W", "U"): "bant",
    ("W", "U", "R"): "jeskai",
    ("U", "B", "G"): "sultai",
    ("B", "R", "W"): "mardu",
    ("R", "G", "U"): "temur",
    ("G", "W", "B"): "abzan",
}

_MONO = {
    ("W",): "mono-white",
    ("U",): "mono-blue",
    ("B",): "mono-black",
    ("R",): "mono-red",
    ("G",): "mono-green",
}

_COLORLESS = {(): "colorless"}


def _build_slug_map() -> dict[tuple[str, ...], str]:
    slug_map: dict[tuple[str, ...], str] = {}
    for table in (_COLORLESS, _MONO):
        slug_map.update(table)

    for colors, name in _GUILDS.items():
        slug_map[_sort_colors(colors)] = name
    for colors, name in _TRICOLOR.items():
        slug_map[_sort_colors(colors)] = name

    # Four- and five-color: no established nicknames used here, so fall
    # back to the literal color letters. UNVERIFIED against live EDHREC.
    from itertools import combinations

    for n in (4, 5):
        for combo in combinations(WUBRG, n):
            key = _sort_colors(combo)
            if key not in slug_map:
                slug_map[key] = "".join(key).lower()

    return slug_map


SLUGS_BY_COLOR_IDENTITY = _build_slug_map()

# Reverse lookup, used when parsing EDHREC responses back into a
# canonical color-identity tuple.
COLOR_IDENTITY_BY_SLUG = {slug: colors for colors, slug in SLUGS_BY_COLOR_IDENTITY.items()}


class UnknownColorIdentityError(ValueError):
    pass


def slug_for_colors(colors: str | tuple[str, ...]) -> str:
    """Return the EDHREC slug for a color identity.

    ``colors`` may be a string like ``"BR"`` or a tuple like ``("B", "R")``.
    Order and case don't matter.
    """
    if isinstance(colors, str):
        colors = tuple(colors.upper())
    invalid = set(colors) - set(WUBRG)
    if invalid:
        raise UnknownColorIdentityError(f"Not valid WUBRG colors: {sorted(invalid)!r}")
    key = _sort_colors(tuple(colors))
    try:
        return SLUGS_BY_COLOR_IDENTITY[key]
    except KeyError:
        raise UnknownColorIdentityError(f"No EDHREC slug known for colors {colors!r}") from None


def all_slugs() -> list[str]:
    """All 32 color-identity slugs, colorless through five-color."""
    return sorted(set(SLUGS_BY_COLOR_IDENTITY.values()))
