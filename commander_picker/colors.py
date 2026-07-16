"""Color identity <-> EDHREC URL slug mapping.

EDHREC groups its commander/theme pages by color identity using slugs
like ``rakdos`` or ``mono-red`` in URLs such as
``https://json.edhrec.com/pages/commanders/rakdos.json``.

**Verified 2026-07-16** against a live response from
``https://json.edhrec.com/pages/commanders/rakdos.json`` — its
``related_info`` block lists all 32 color-identity slugs directly, so
every entry below (including the four/five-color names, which were
previously an unverified guess) is now confirmed against real EDHREC
data rather than inferred.
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

# Four-color nicknames (from the Alara block's Nephilim) and the
# five-color catch-all. Confirmed against a live EDHREC response's
# `related_info` block.
_FOUR_FIVE_COLOR = {
    ("W", "U", "B", "R"): "yore-tiller",
    ("U", "B", "R", "G"): "glint-eye",
    ("B", "R", "G", "W"): "dune-brood",
    ("R", "G", "W", "U"): "ink-treader",
    ("G", "W", "U", "B"): "witch-maw",
    ("W", "U", "B", "R", "G"): "five-color",
}


def _build_slug_map() -> dict[tuple[str, ...], str]:
    slug_map: dict[tuple[str, ...], str] = {}
    for table in (_COLORLESS, _MONO):
        slug_map.update(table)

    for colors, name in _GUILDS.items():
        slug_map[_sort_colors(colors)] = name
    for colors, name in _TRICOLOR.items():
        slug_map[_sort_colors(colors)] = name
    for colors, name in _FOUR_FIVE_COLOR.items():
        slug_map[_sort_colors(colors)] = name

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
