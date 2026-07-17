# Commander Picker

Help decide which EDH/Commander deck to build next. Pulls commander
popularity and archetype/theme data from EDHREC, lets you filter down
to a candidate pool (colors, archetype, an "underbuilt" deck-count
ceiling), then will run a swipe-style head-to-head picker with Elo
ratings to narrow the pool to a ranked shortlist.

## Status

Phases 1–4 are done: EDHREC data ingestion (live-verified — a real
`update-data` run pulls 3,797+ commanders with correct color
identities, deck counts, and theme tags), filtering / candidate pools,
the Elo-style swipe picker, and a web UI on top of the same engine —
playable from the terminal (`play`) or a browser (`serve`). Phase 5
(card images from Scryfall, plus a UX pass on the web UI — typed
deck-count entry, editable duel pool size, total-vs-capped match
counts) is partially done — see `PLAN.md`.

**Known gap:** this dev sandbox's egress policy blocks edhrec.com
(403) — `update-data` was verified by the project owner running it
from their own machine and sharing back real captured responses
rather than in this environment directly. If you're picking this up
in a similarly restricted sandbox, the same approach applies: get
someone with real network access to run `update-data` and sanity
check `data/commanders.db`.

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

This also fetches Scryfall's card-art data (a separate, larger
download — Scryfall's full `oracle_cards` bulk file) and populates
each commander's `image_url`, used by the web UI's duel cards and
results ledger. **Unverified against live Scryfall** in this dev
sandbox (same egress block as edhrec.com) — see PLAN.md Phase 5.

Useful flags:

- `--force` — bypass the freshness cache and re-fetch everything.
- `--colors azorius,rakdos` — only fetch/rebuild specific color slugs.
- `--themes tokens,aristocrats` — only fetch/rebuild specific theme slugs.
- `--skip-images` — skip the Scryfall card-art fetch (faster, no images
  in the web UI). A failed Scryfall fetch (e.g. unreachable) doesn't
  abort the run either way — you just end up without images.

To see the full list of recognized slugs:

```bash
commander-picker list-colors
commander-picker list-themes
```

Both `data/edhrec/*.json` and `data/commanders.db` are gitignored —
regenerated locally rather than committed.

## Filtering a candidate pool

Once `data/commanders.db` exists, preview a filtered pool before
running a picker session against it:

```bash
commander-picker pool --colors BRG --color-mode subset --max-decks 10000 --themes tokens,aristocrats
```

- `--colors` — allowed colors, e.g. `BRG` (default: no color filter).
- `--color-mode` — `subset` (commander's identity fits within
  `--colors`, the default) or `exact` (identity must match exactly).
- `--max-decks` / `--min-decks` — deck-count range (default: max
  10,000, no minimum) — this is the "underbuilt commander" filter.
- `--themes` — comma-separated theme slugs to filter by.
- `--themes-mode` — `any` (OR, default) or `all` (AND) across
  `--themes`.
- `--pool-size` / `--min-pool-size` — bounds on the returned pool
  (default: up to 40, error below 4). When more than `--pool-size`
  commanders match, a random sample is taken rather than always the
  highest deck counts within the filtered range — the point is
  variety, not always seeing the same top-of-range commanders.

## Playing a picker session

Once you have a filtered pool you like, start an interactive session:

```bash
commander-picker play --colors BRG --themes tokens
```

Each round shows two candidates; type `1` or `2` to pick your
favorite, `f` to finish early and see the final ranking, or `q` to
pause (the session stays saved and resumable). Ratings update via a
standard Elo formula after each pick. A suggested round count (roughly
`pool_size * log2(pool_size)`) is shown as guidance, not a hard
cutoff — keep going past it for finer-grained results, or stop
whenever you're satisfied.

```bash
commander-picker sessions                 # list all sessions (active + finished)
commander-picker resume <session-id>       # continue a paused session
commander-picker results <session-id>      # show current/final ranking without playing
```

`play` accepts the same filter flags as `pool` (`--colors`,
`--color-mode`, `--max-decks`, `--min-decks`, `--themes`,
`--themes-mode`, `--pool-size`, `--min-pool-size`).

Sessions live in `data/sessions.db` — a separate file from
`commanders.db`, so re-running `update-data` never wipes your
in-progress or past picker sessions. Also gitignored.

## Web UI

The same picker, in a browser instead of the terminal:

```bash
commander-picker serve
```

Then open http://127.0.0.1:8000. Filter by color — with a toggle for
**any combo within your selected colors** (picking B+R shows mono-B,
mono-R, and BR) vs. **exact colors only** (picking B+R shows only BR)
— an exact-or-slider-adjusted deck-count ceiling, and an editable duel
pool size (the live preview shows both the total commanders matching
your filters and how many will actually be sampled into the duel —
the two can differ once a filter matches more than the pool size).
Tap through duels — with card art when Scryfall images are available
— and see final standings. Same Elo engine and `data/sessions.db` as
`play`/`resume`/`results`, so sessions started in one are visible from
the other. Flags: `--host`, `--port`, `--reload` (auto-restart on code
changes, for development).

Local-only, no auth, no rate limiting — fine for a single-user local
tool, would need attention before exposing beyond localhost.

API endpoints, if you want to hit them directly or build another
client: `GET /api/themes`, `POST /api/pool`, `POST /api/sessions`,
`GET /api/sessions`, `GET /api/sessions/{id}`, `GET
/api/sessions/{id}/pairing`, `POST /api/sessions/{id}/pick`, `POST
/api/sessions/{id}/finish`, `GET /api/sessions/{id}/results`.

## Project layout

```
commander_picker/
  colors.py         # color-identity <-> EDHREC URL slug mapping (32 combos)
  themes.py         # known EDHREC archetype/theme page slugs
  edhrec_client.py  # fetch + cache EDHREC color/theme pages, with pagination
  scryfall_client.py # fetch Scryfall bulk data, build name -> art_crop image lookup
  db.py             # parse cached pages into data/commanders.db (SQLite)
  pool.py           # filter commanders.db into a bounded candidate pool
  elo.py            # Elo rating math + pairing selection (no DB dependency)
  sessions.py       # persist picker sessions in data/sessions.db
  cli.py            # `commander-picker` command-line entry point
  web/
    app.py           # FastAPI app (JSON API + serves the static frontend)
    static/          # index.html / app.js / style.css — no build step
tests/
  fixtures/          # hand-built/captured sample EDHREC pages for offline tests
  test_colors.py
  test_edhrec_client.py
  test_scryfall_client.py
  test_db.py
  test_pool.py
  test_elo.py
  test_sessions.py
  test_web.py
PLAN.md              # phased project plan + progress notes
```

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

Tests run entirely offline against hand-built fixtures in
`tests/fixtures/`, so they don't require network access to EDHREC.
