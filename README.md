# Commander Picker

Help decide which EDH/Commander deck to build next. Pulls commander
popularity and archetype/theme data from EDHREC, lets you filter down
to a candidate pool (colors, archetype, an "underbuilt" deck-count
ceiling), then will run a swipe-style head-to-head picker with Elo
ratings to narrow the pool to a ranked shortlist.

## Status

Fully built and live-verified: EDHREC data ingestion (a real
`update-data` run pulls 3,800+ commanders with correct color
identities, deck counts, theme tags, and card art), filtering /
candidate pools, the Elo-style swipe picker with cross-session
persistent ratings and an all-time leaderboard, a web UI on top of
the same engine, and a Docker deployment for a public URL — see
`PLAN.md` for architecture notes and what's not yet started.

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
each commander's `image_urls`, used by the web UI's duel cards and
results ledger. Most commanders get one image; Partner/Background
pairs (EDHREC's "A // B" combined name) and double-faced/transform
commanders get two, shown side by side — the two halves of a
partner pair are separate Scryfall cards, while a transform card's
front and back are two faces of the same card.

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
standard Elo formula after each pick. A session automatically finishes
once it reaches its target round count (roughly `pool_size *
log2(pool_size)`) and shows the final ranking — use `f` any time
before that to stop sooner.

```bash
commander-picker sessions                 # list all sessions (active + finished)
commander-picker resume <session-id>       # continue a paused session
commander-picker results <session-id>      # show current/final ranking without playing
commander-picker leaderboard              # all-time Elo across every session ever played
commander-picker leaderboard --colors BR --color-mode exact  # filter it by color, same as pool/play
commander-picker leaderboard --reset      # permanently erase all-time ratings (asks to confirm; --yes skips the prompt)
```

`play` accepts the same filter flags as `pool` (`--colors`,
`--color-mode`, `--max-decks`, `--min-decks`, `--themes`,
`--themes-mode`, `--pool-size`, `--min-pool-size`).

### Bracket mode

An alternative to the continuous duel above: a classic single-elimination
tournament, one loss and you're out, ending in a single champion instead
of a full ranking.

```bash
commander-picker play --mode bracket --pool-size 16 --colors BRG
```

- `--pool-size` must be an exact power of two (4, 8, 16, 32, ...) --
  bracket mode rejects anything else rather than padding with byes or
  silently trimming.
- Round 1 is seeded by each commander's current all-time rating (highest
  vs. lowest, like a real tournament bracket), so favorites can't meet
  until later rounds.
- No `f` to finish early -- a partial bracket has no meaningful champion,
  so play (or `resume`) it out to the final.
- Each match still updates ratings and the all-time leaderboard, but
  with a gentler K-factor than duel mode (see `PLAN.md`'s "Bracket mode"
  note for why) -- a bracket loser only ever gets one comparison for the
  whole session, unlike duel mode's many.
- `commander-picker results <id>` and `resume <id>` both show the full
  bracket tree (who played whom, who won, and the champion once decided)
  instead of a rating-sorted list.

Sessions live in `data/sessions.db` — a separate file from
`commanders.db`, so re-running `update-data` never wipes your
in-progress or past picker sessions. Also gitignored.

Ratings persist across sessions, not just within one: each
commander's Elo carries forward from `data/sessions.db`'s
`commander_ratings` table and keeps refining the more it's picked,
instead of resetting to 1000 every time you start a new session.
`commander-picker leaderboard` (or the web UI's "All-time
leaderboard" link) shows this cross-session ranking, separate from
any one session's own final standings.

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

A **Duel / Bracket** toggle on the filter screen switches to bracket
mode (see "Bracket mode" above) -- picking Bracket swaps the free pool-size
input for a row of power-of-two size presets (4/8/16/32/64), disabling
any preset larger than what your current filters actually match. During
a bracket you'll see a live compact tree of the matches played so far
above the duel cards, and the final screen shows the champion plus the
full bracket instead of a rating-sorted list.

Local-only, no auth, no rate limiting — fine for a single-user local
tool, would need attention before exposing beyond localhost.

API endpoints, if you want to hit them directly or build another
client: `GET /api/themes`, `POST /api/pool`, `POST /api/sessions`
(`mode: "duel"` or `"bracket"` in the body), `GET /api/sessions`, `GET
/api/sessions/{id}`, `GET /api/sessions/{id}/pairing`, `POST
/api/sessions/{id}/pick`, `POST /api/sessions/{id}/finish` (bracket
sessions 400 -- no early finish), `GET /api/sessions/{id}/results`, `GET
/api/sessions/{id}/bracket` (full bracket tree + champion, bracket mode
only), `GET /api/leaderboard` (all-time ranking; optional `?limit=`
default 100, `?colors=`/`?color_mode=` same as `/api/pool`), `DELETE
/api/leaderboard` (permanently erases all-time ratings -- the web UI
confirms before calling this, the API itself doesn't ask).

## Deploying

The included `Dockerfile` builds `data/commanders.db` **during the
image build** (`RUN commander-picker update-data`), so the resulting
container is fully self-contained — no separate data-fetching step
and no repo clone needed by anyone using the deployed link. This
means the *build* needs to happen somewhere with real internet
access to edhrec.com and api.scryfall.com.

Recommended: **Render**, free Docker-based Web Service, no credit
card required.

1. Push this repo to GitHub (already done if you're reading this from
   the repo).
2. render.com → sign in with GitHub → "New +" → "Web Service" →
   select this repo.
3. Confirm Render detected **Docker** as the environment (not a
   Python buildpack — that would skip the Dockerfile and the
   baked-in `update-data` step).
4. Branch: whichever you want deployed. Instance type: Free. `PORT`
   is injected automatically and the Dockerfile's `CMD` already reads
   it, so no environment variables are *required* — but see below
   for the two that make session/Elo data survive redeploys.
5. Create the service and watch the build log — `update-data` runs
   here, against Render's real internet access; the Scryfall bulk
   download is the slowest part.
6. Once "Live", Render shows your public `https://commander-picker-957g.onrender.com`
   URL — open it from any phone or PC browser, no further setup.

Known free-tier limitations: the service sleeps after ~15 min idle
(30-60s cold start on the next visit), and there's no persistent
disk. `data/commanders.db` is unaffected by this — it's rebuilt
fresh from `update-data` on every deploy — but `data/sessions.db`
(picker sessions + the cross-session Elo leaderboard) would reset on
every redeploy or sleep/wake restart if left as a plain local file.
Every future `git push` to the connected branch auto-rebuilds and
redeploys.

### Persisting sessions/Elo data with Turso

To keep `sessions.db`'s data (in-progress sessions, the all-time Elo
leaderboard) across redeploys and restarts, point it at a
[Turso](https://turso.tech) database instead of a local file:

1. Sign up at turso.tech (GitHub login works) and create a database
   from their web dashboard — no CLI needed (their CLI requires WSL
   on Windows anyway).
2. From the dashboard, copy the database URL
   (`libsql://<name>.turso.io`) and generate an auth token.
3. On Render: your service's Environment tab → add `TURSO_DATABASE_URL`
   and `TURSO_AUTH_TOKEN`.
4. Locally, if you want `commander-picker play`/`serve` to hit the
   same remote database instead of `data/sessions.db`, set the same
   two environment variables in your shell before running the
   command. Leave them unset for local dev against the plain local
   file — `sessions.connect()` only reaches for Turso when
   `TURSO_DATABASE_URL` is set and no explicit `db_path` was passed.

`commanders.db` (the EDHREC/Scryfall catalog) intentionally stays a
local file rebuilt on every deploy — it never needed persistence,
only `sessions.db` did.

## Project layout

```
commander_picker/
  colors.py         # color-identity <-> EDHREC URL slug mapping (32 combos)
  themes.py         # known EDHREC archetype/theme page slugs
  edhrec_client.py  # fetch + cache EDHREC color/theme pages, with pagination
  scryfall_client.py # fetch Scryfall bulk data, build name -> full card image lookup
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
