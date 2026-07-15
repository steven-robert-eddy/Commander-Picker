# Commander Picker

Help decide which EDH/Commander deck to build next. Pulls commander
popularity and archetype/theme data from EDHREC, lets you filter down
to a candidate pool (colors, archetype, an "underbuilt" deck-count
ceiling), then will run a swipe-style head-to-head picker with Elo
ratings to narrow the pool to a ranked shortlist.

## Status

Phase 1 (EDHREC data ingestion) is done: fetch + cache EDHREC pages,
load them into a local SQLite DB. Phases 2–5 (filtering, the picker
engine, and the web UI) are not started yet — see `PLAN.md`.

**Known gap:** this dev sandbox's egress policy blocks edhrec.com
(403), so `update-data` has never actually been run against live data
in this environment — only verified offline against hand-built test
fixtures (`tests/fixtures/`). The exact EDHREC JSON response shape
assumed by `edhrec_client.py` / `db.py` is a best-effort guess and
needs a live sanity check once this (or another) environment can
actually reach edhrec.com. See the docstrings in those two files for
what to check and fix up if the real shape differs.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Fetching data

EDHREC has no official public API, but its own frontend consumes JSON
documents from `json.edhrec.com`. This fetches one page per
color-identity combo (32 total: colorless, 5 mono, 10 guilds, 10
shards/wedges, 6 four-color, 1 five-color) and one page per known
archetype/theme (tokens, aristocrats, +1/+1 counters, voltron, ...),
caching each locally under `data/edhrec/` with a 24h freshness window:

```bash
commander-picker update-data
```

This also (re)builds `data/commanders.db`, a SQLite database with one
row per commander (name, color identity, deck count, EDHREC salt
score, URL) plus a `commander_themes` table recording which
archetype/theme pages each commander appeared on.

Useful flags:

- `--force` — bypass the freshness cache and re-fetch everything.
- `--colors azorius,rakdos` — only fetch/rebuild specific color slugs.
- `--themes tokens,aristocrats` — only fetch/rebuild specific theme slugs.

To see the full list of recognized slugs:

```bash
commander-picker list-colors
commander-picker list-themes
```

Both `data/edhrec/*.json` and `data/commanders.db` are gitignored —
regenerated locally rather than committed.

## Project layout

```
commander_picker/
  colors.py         # color-identity <-> EDHREC URL slug mapping (32 combos)
  themes.py         # known EDHREC archetype/theme page slugs
  edhrec_client.py  # fetch + cache EDHREC color/theme pages
  db.py             # parse cached pages into data/commanders.db (SQLite)
  cli.py            # `commander-picker` command-line entry point
tests/
  fixtures/          # hand-built sample EDHREC pages for offline tests
  test_colors.py
  test_edhrec_client.py
  test_db.py
PLAN.md              # phased project plan + progress notes
```

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

Tests run entirely offline against hand-built fixtures in
`tests/fixtures/`, so they don't require network access to EDHREC.
