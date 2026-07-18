# Commander Picker — Plan & Progress

Help decide which EDH/Commander deck to build next. Pulls commander
popularity and archetype/theme data from EDHREC, lets you filter down
to a candidate pool (colors, archetype, an "underbuilt" deck-count
ceiling), then runs a swipe-style head-to-head picker with Elo ratings
to narrow the pool to a ranked shortlist — playable from the terminal
or a browser, with ratings that persist and compound across sessions.

Stack: Python, SQLite (local cache + queryable DB), Turso (managed
libSQL) for session storage, EDHREC's JSON data as the source, Scryfall
for card art. Standalone project — no dependency on the sibling
`commander-synergy` repo's package, though the two may link later
(e.g. "find synergy for this pick" once a commander is chosen).

## Status: all core functionality done and live-verified

- **Data ingestion** (`edhrec_client.py`, `colors.py`, `themes.py`,
  `db.py`): fetches all 32 color-identity combos and known
  archetype/theme pages from `json.edhrec.com`, paginates past each
  page's ~100-entry cap, and builds `data/commanders.db`. A full run
  pulls 3,800+ real commanders with correct color identities, deck
  counts, and theme tags.
- **Card art** (`scryfall_client.py`): resolves each commander's
  Scryfall image URL(s) at `update-data` time and stores them
  directly in `commanders.db` — Partner/Background pairs and
  double-faced/transform commanders get both images. The running app
  never touches Scryfall's large raw bulk file again after that.
- **Filtering** (`pool.py`): color (subset or exact match),
  deck-count range, theme, bounded/randomly-sampled pool size.
- **Picker engine** (`elo.py`, `sessions.py`): Elo-style swipe/rank
  feed — random pairing early, rating-adjacent pairing later, a
  session auto-finishes once it hits its target round count
  (`pool_size * log2(pool_size)`).
- **Persistent, cross-session ratings**: a commander's Elo carries
  forward from session to session via a `commander_ratings` table in
  `sessions.db`, instead of resetting to 1000 every time. An all-time
  leaderboard (CLI, API, and web UI) shows this cross-session
  ranking, filterable by color the same way the duel picker is.
- **Sessions/Elo data on Turso**: `sessions.py` connects to a managed
  Turso (libSQL) database when `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`
  are set, instead of a plain local file — so picker sessions and the
  all-time leaderboard survive redeploys/restarts on hosts with no
  persistent disk (e.g. Render's free tier). Falls back to the local
  file when unset, so local dev/tests are unaffected.
- **CLI** (`cli.py`): `update-data`, `pool`, `play`, `resume`,
  `sessions`, `results`, `leaderboard`, `list-colors`, `list-themes`,
  `serve`.
- **Web UI** (`web/app.py`, `web/static/`): FastAPI + plain HTML/JS,
  no build step. Filter → duel → results → all-time leaderboard, with
  a lightbox for full-size card views. Same backend/data as the CLI.
- **Deployment**: a `Dockerfile` builds `commanders.db` during the
  image build itself (so the container ships fully self-contained),
  deployable to a free Render Web Service — see README's "Deploying"
  section for the runbook.

See `README.md` for setup and usage. The sections below cover
architecture notes and decisions worth knowing if you're extending
this project, not a play-by-play changelog.

## Architecture notes

- **Two separate SQLite-family stores, deliberately**: `commanders.db`
  (the catalog) is a local file, fully dropped and rebuilt on every
  `update-data` run; `sessions.db` (picker sessions + the all-time
  leaderboard) persists independently — locally as a SQLite file by
  default, or on Turso when configured — so rebuilding the catalog
  never wipes session history or ratings.
- **`sessions.py`'s Turso path is an adapter, not a rewrite**: libSQL
  is a SQLite fork, so the schema and every query (upserts, a
  `ROW_NUMBER() OVER (PARTITION BY ...)` window function, etc.) are
  unchanged between the two backends. The `libsql` Python package's
  one real gap versus stdlib `sqlite3` is no `row_factory` (rows come
  back as plain tuples) and no direct cursor iteration — `_TursoRow`/
  `_TursoCursor`/`_TursoConnection` restore just those two behaviors,
  isolated entirely inside `connect()`, so no other function in the
  module branches on which backend it's talking to. An **explicit**
  `db_path` argument to `connect()` always wins and stays plain local
  sqlite3 regardless of ambient env vars — only the zero-arg call
  `cli.py`/`web/app.py` use in production auto-detects Turso — so a
  developer's own shell env can't accidentally redirect a test run at
  the real remote database.
- **Color matching** (`pool._color_identity_matches`, reused directly
  by `sessions.get_leaderboard`): `subset` mode means a commander's
  identity fits within the selected colors (e.g. picking B+R shows
  mono-B, mono-R, and BR); `exact` mode means the identity matches
  exactly. Colorless commanders are stored as `color_identity=""` and
  normalized to the pseudo-color `"C"` for comparison in both modes.
- **Card images**: `image_urls` is a list, not a single URL — most
  commanders get one image, Partner/Background pairs and
  double-faced/transform commanders get two (resolved once at
  `update-data` time, not recomputed per-request). The duel/results/
  leaderboard screens all size these consistently regardless of
  count (a 1-image commander doesn't balloon just because its
  opponent has fewer images to show).
- **Round count is a hard cutoff, not a suggestion**: a session
  auto-finishes once `rounds_completed` reaches `target_round_count`,
  both proactively (`next_pairing`) and reactively (`record_pick`),
  so a session can't drift past its target from either code path.
- **Cross-session Elo**: `commander_ratings` (name, rating,
  games_played, updated_at) is separate from each session's own
  `candidates.rating` snapshot. `create_session` seeds each
  candidate's starting rating from `commander_ratings` when it has
  history; `record_pick` updates both the session-local rating and
  the global one on every single pick, so a paused/abandoned
  session's partial progress still counts toward the all-time rating.
- **No auth / no multi-user support yet** — deliberate, not
  forgotten. `GET /api/sessions` and the leaderboard currently return
  global state with no per-user scoping; fine for a single-user or
  personal-link deployment, but two simultaneous strangers would
  share one global session list. Real accounts (auth, `/api/sessions`
  scoped to the logged-in user, a user column on `sessions.db`) are
  the planned fix once this needs to support more than one person —
  no longer blocked on moving off local SQLite first, since
  `sessions.db` can already live on Turso.

## Not yet started

- Session history across visits (which commanders have already been
  shown/picked/rejected before, so repeat sessions can exclude recent
  picks).
- Cross-link to `commander-synergy`: once a commander is chosen, jump
  straight into that project's synergy finder for it.
- Real multi-user accounts (see above).
- Backfilling the all-time leaderboard from pre-leaderboard-feature
  session history: the ~65 local sessions played before
  `commander_ratings` existed have their full `comparisons` history
  (every winner/loser pair with a timestamp) but no reconstructed
  rating — could be replayed through the Elo math to backfill, but
  deliberately skipped when Turso was set up (started that leaderboard
  fresh instead, by request) — the local history remains available if
  this is revisited later.

## Known limitations

- EDHREC's `THEME_SLUGS` list is a curated guess of which archetype
  tag pages exist — `update-data` skips any slug that 404s, so this
  degrades gracefully but the list is worth trimming/correcting
  against EDHREC's real tag list at some point.
- EDHREC's "num decks" figure is a moving target (updates
  continuously) — the cache freshness window keeps this reasonably
  fresh without hammering the site on every session.
- Elo K-factor and round-count scaling are hand-picked priors — worth
  tuning once there's real usage to observe.
- Render's free tier has no persistent disk. `commanders.db` is
  unaffected since it's rebuilt fresh on every deploy anyway;
  `sessions.db` only survives redeploys/restarts if `TURSO_DATABASE_URL`/
  `TURSO_AUTH_TOKEN` are set on the service — see README's Deploying
  section. Without them it falls back to a local file that resets on
  every redeploy, same as before Turso was added.

## Repo/branch notes

- Working repo: `steven-robert-eddy/commander-picker`.
- All work happens on branch `claude/mtg-commander-picker-w5iar6`.
- Sibling repos: `commander-synergy` (mechanical synergy finder given
  a commander name, Scryfall-based, fully built — see its own
  PLAN.md) and `commander-companion` (currently empty/unused).
