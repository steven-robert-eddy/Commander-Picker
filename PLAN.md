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
`commander-synergy` repo's package; that project isn't in a state worth
linking to right now, so cross-linking is on hold (see "Someday" below).

Direction, as of 2026-07-19: staying a personal, single-user tool for
now — the goal is a genuinely solid product before expanding who it's
for. Real multi-user accounts are a deliberate "someday" goal, not
dropped, just intentionally after that.

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
- **Bracket mode**: an alternative single-elimination tournament mode
  (CLI: `play --mode bracket`, web: a Duel/Bracket toggle on the
  filter screen) alongside the continuous duel mode above — crowns one
  champion instead of producing a full ranking. Requires a pool size
  that's an exact power of two (4, 8, 16, ...; enforced rather than
  padded with byes or trimmed). Round 1 is seeded by current all-time
  rating via `elo.bracket_seed_order` (the standard recursive
  tournament-seeding permutation), so top-rated commanders can't meet
  until later rounds. Each match still updates both the session-local
  rating and the all-time leaderboard, but through `elo.BRACKET_K_FACTOR`
  (16, half of duel's `K_FACTOR`) instead of the duel K-factor: a
  bracket loser gets exactly one comparison for the whole session (no
  later matches to average a bad result out over, unlike duel mode's
  many comparisons per commander), so the gentler K-factor damps that
  extra variance while still letting bracket results meaningfully
  inform the leaderboard. `sessions.py`'s `bracket_matches` table stores
  the full tree (every round's slots, seeded upfront so later rounds
  show "TBD" placeholders before they're reached) — see
  `sessions.create_session`/`record_bracket_pick`/`get_bracket`.
- **Card details: rank, mana cost, type line, price** (`db.py`,
  `scryfall_client.py`, `pool.py`): EDHREC's per-commander `rank` (its
  position on the page it was found on) is captured alongside
  `num_decks`; `scryfall_client.build_card_meta_lookup`/
  `resolve_card_meta` extract mana cost, type line, and USD price from
  the same bulk `oracle_cards.json` already downloaded for card art (a
  second in-memory pass over that file, kept as an additive pair of
  functions alongside `build_image_lookup`/`resolve_image_urls` rather
  than merged into them, so neither's existing tests/call sites had to
  change shape). Shown on duel cards as a rank badge and mana-cost pips
  (reusing the same Scryfall symbol SVGs as color-identity pips). The
  price filter (`PoolFilters.max_price`, CLI `--max-price`, web slider)
  is opt-in and **permissive on missing price data** — a commander with
  no price (common for unresolved Partner/Background halves) is never
  excluded even when the filter is active, since "we don't know" is
  friendlier than silently shrinking the pool over a data gap. The web
  UI's price slider was briefly shown, then hidden again (no data-quality
  issue — just simplifying the UI for now) — `--max-price`/`max_price`
  stay fully working on the CLI and API.
- **Archetype/theme filter**: briefly re-enabled in the web UI, then
  re-hidden after live testing confirmed the same limitation that hid it
  the first time (see "Known limitations" below) — EDHREC's tag pages
  just don't carry enough signal yet. Still fully built and available via
  the CLI/API (`pool --themes`, `play --themes`); see "Roadmap" for the
  theme-filter UI decision this is waiting on.
- **Deckbuilder links**: the lightbox (opened from a results/leaderboard
  row) shows "View on EDHREC" (reliable, uses the stored `edhrec_url`)
  plus best-effort "Search Moxfield"/"Search Archidekt" links —
  deliberately placed in the lightbox rather than on the duel screen's
  card buttons or the clickable rank-list rows themselves, to avoid
  nesting another tap target inside an existing one (see the mobile
  reset-button bug from earlier in this project for why that's worth
  avoiding). The Moxfield/Archidekt query-string format couldn't be
  verified live from this sandbox — worth a click-test once deployed.
- **Keyboard shortcuts**: `1`/`2` or the arrow keys pick a duel card on
  the web UI, mirroring the CLI's `1`/`2` input.
- **Undo last pick** (duel mode only): reverts the most recently recorded
  pick exactly -- both candidates' session-local ratings, the all-time
  `commander_ratings` entry (deleted outright if that pick was the
  commander's first-ever game, restored to its prior value/games_played
  otherwise), and `rounds_completed` (un-finishing the session if that
  pick was what completed it). `sessions.py`'s `comparisons` table now
  stores each pick's pre-pick session-local and all-time ratings
  (`*_rating_before` columns) specifically so this can restore exact
  values instead of trying to invert the Elo formula. Repeatable --
  each call reverses one more pick, like a normal undo stack. **Not
  supported for bracket sessions**: a bracket pick also propagates its
  winner into the next round's slot, and safely undoing that would need
  to confirm nothing downstream has consumed that winner yet -- a real
  feature on its own, not yet built. CLI: `u` during `play`/`resume`.
  Web: an "← Undo" button next to "Finish now" (disabled until there's
  something to undo), or press `u`.
- **Web UI session list/resume**: a "My sessions →" link (filter screen)
  lists every session (`GET /api/sessions`, already existed for the
  CLI's `sessions` command -- no new backend needed), tapping an active
  one resumes it (fetches its current pairing via the same
  `GET /api/sessions/{id}/pairing` the duel screen already polls, mode-
  aware since `_pairing_payload` already dispatches on duel vs. bracket)
  and a finished one re-shows its results/bracket tree. `startSession`
  and this share a new `enterDuelScreen(info, pairing)` helper so both
  entry points toggle the same finish/undo/bracket-tree visibility and
  land on the correctly-resumed round (undo's enabled/disabled state
  falls out of `renderPairing`'s existing `pairing.round <= 1` check, so
  resuming mid-session correctly re-enables it with no extra code).
- **Custom commander list** (web UI only): a "Pool source: Filtered /
  Custom list" toggle on the filter screen swaps the color/deck-count
  filter for a search box (`GET /api/commanders/search?q=...`, name
  substring match) with autocomplete showing colors and deck count per
  result. Adding commanders builds a list that starts a session via a
  new `POST /api/sessions/custom` (`pool.commanders_by_names` -- exact-
  name lookup, order-preserving, 422 on unknown/duplicate names) instead
  of the filter-based `/api/sessions`. Works for duel (>=2 commanders)
  and bracket (exact power-of-two count, same `elo.is_valid_bracket_size`
  rule as filtered bracket sizing, no byes/padding). No changes needed to
  `sessions.create_session`, Elo, undo, bracket engine, or resume --
  they already operate on a plain `list[Commander]` regardless of how it
  was built. CLI equivalent (`--names`) intentionally deferred.
- **Salt score + richer per-commander themes**: confirmed live
  2026-07-19 against `.../pages/commanders/rakdos-lord-of-riots.json`
  that a commander's own EDHREC detail page (same URL template as color
  pages, just with the commander's own `sanitized` slug) is flat at the
  top level (no `container` wrapper) with salt at `card.salt` and
  deck-count-weighted tags at `panels.taglinks` -- far richer than the
  shallow ~30-commander tag-page lists this app has scraped since early
  on. New `commander-picker enrich-commanders [--limit N] [--force]`
  CLI command fetches+caches each commander's detail page (deliberately
  never touches `commanders.db` directly, only `edhrec_client`'s
  on-disk cache -- `db.build_database()` rebuilds the whole DB from
  scratch every time, so writing enrichment straight into it would get
  silently wiped by the next ordinary `update-data` run; this command
  is the same cache-first pattern color/theme pages already use). Run
  `update-data` afterward to fold it in: `db.load_commanders()` applies
  each commander's cached detail page last (if present), setting `salt`
  and merging its top `TOP_TAGS_PER_COMMANDER` (10) tags by deck count
  into `themes`, alongside whatever the shallow tag pages already
  contributed. `GET /api/themes` now returns `pool.list_known_themes`
  (a `SELECT DISTINCT theme FROM commander_themes`) instead of the
  hand-curated `themes.py::THEME_SLUGS` list, so the API reflects real
  data as soon as it exists; `THEME_SLUGS` itself is untouched and
  still drives which shallow tag pages get fetched by default. Data
  plumbing only this pass -- no salt filter, no theme-filter UI
  re-enablement (see Roadmap).
- **Power-level badge**: the first item picked off the "Next:
  Personalization" roadmap tier. The same cached per-commander detail
  page fetched for salt/themes also carries `bracket_counts` -- EDHREC's
  own distribution of which Commander Bracket (1 Exhibition / 2 Core /
  3 Upgraded / 4 Optimized / 5 cEDH) real decks running that commander
  fall into. `db.py`'s `_apply_commander_detail` now also sets a new
  `power_level` field to the dominant bracket (highest deck count),
  stored as a `power_level` column in `commanders.db`. Threaded through
  the same path every other commander field follows: `CommanderRecord`
  -> `pool.Commander` (`_filtered_candidates`/`commanders_by_names`) ->
  `sessions.py`'s `candidates` table (new column, with a guarded
  `ALTER TABLE` migration since `sessions.db` persists across runs,
  unlike `commanders.db`) -> `CandidateDetail`/`RankedCommander` -> API
  responses (no endpoint changes needed, they already `asdict()` these
  dataclasses) -> a `.tag`-styled "Bracket N · <name>" badge in
  `app.js`'s `cardInnerHTML` (duel/bracket cards) and `renderRankList`
  (duel-mode session results only -- the all-time leaderboard's
  `GlobalRanking` doesn't carry this field, out of scope for this pass).
  Data + a visible badge only, same scoping as when salt/rank first
  shipped -- no filter yet (still on the Roadmap).
- **32-deck challenge tracker**: a personal planning tool for building
  one Commander deck per color-identity combination, riding entirely on
  data this app already produces -- not a new rating/Elo concept.
  Deliberately built inside Commander Picker rather than as a separate
  project: `colors.py::all_slugs()` already defines exactly the 32
  combos with a full slug<->color-tuple mapping. Two new `sessions.db`
  tables, `challenge_tracker` (slug -> status/notes) and
  `challenge_commanders` (slug -> a short shortlist of candidate
  commanders, at most one marked chosen) -- entries aren't pre-seeded,
  `get_challenge_tracker` synthesizes all 32 at read time by overlaying
  whatever rows exist onto `colors.all_slugs()`. New endpoints:
  `GET /api/challenge`, `PUT /api/challenge/{slug}` (status/notes,
  full overwrite not a patch), `POST`/`DELETE .../commanders[/choose]`.
  Ties into existing session data: `api_finish`/`api_results`/
  `api_bracket` responses gain a `winner_challenge_slug`
  (`colors.slug_for_colors` on the winning commander's own color
  identity -- no need to detect "was this session filtered to one
  combo," the winner's own identity is what matters), which the results
  screen uses to show a one-click "Add {commander} as an option for
  {combo}?" nudge if it's not already listed -- purely additive, never
  auto-chooses or overwrites an existing entry. New "32-deck challenge
  →" screen (`#screen-challenge`) lists all 32 combos with a status
  dropdown and add/remove/choose controls per candidate. Started small
  per the user's request (status + a shortlist, not a single locked-in
  commander) with `notes` already in the schema for a future richer-
  planning pass (decklist link, budget, completion date) without a
  migration. Follow-up pass, per user feedback:
  `colors.py::all_slugs()` now orders mono -> guild -> shard/wedge ->
  four-color -> five-color -> colorless (`_ordering_key`, count-based
  with colorless sorting last) instead of alphabetically -- affects
  every consumer of `all_slugs()` (CLI's `list-colors`, the challenge
  tracker, `edhrec_client.fetch_all_pages`'s default color-fetch order),
  all cosmetic-only changes elsewhere. Candidates now show real card art
  (new `pool.commander_images_by_name` bulk-looks-up image_urls/
  color_identity by name against the catalog DB, since
  `challenge_commanders` only stores names -- `web/app.py`'s
  `_enrich_challenge_entries` joins this in at the API layer for
  `GET /api/challenge`, degrading gracefully to no-art if a name has no
  catalog match or the catalog isn't built yet). Manually adding a
  candidate reuses the exact same search-as-you-type autocomplete as
  the custom-list feature (`GET /api/commanders/search`). Initially
  built as one dropdown per combo row (32 separate scoped searches),
  then simplified per user feedback to a **single search box** at the
  top of the screen instead: a new `POST /api/challenge/commanders`
  (`{"commander_name", "color_identity"}`) determines which of the 32
  combos a result belongs to itself, via `colors.slug_for_colors` on
  the color identity the search result already carries -- no "which
  row's search box" decision for the user, since a commander's own
  colors are what decide that. The row it lands in briefly highlights
  (`app.js`'s `highlightChallengeRow`) so it's obvious where it went.
  The per-slug `POST /api/challenge/{slug}/commanders` endpoint stays
  too (still used by the results-screen nudge, which already knows the
  exact slug from `winner_challenge_slug`).
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
  `sessions.reset_leaderboard()` (CLI: `leaderboard --reset`, API:
  `DELETE /api/leaderboard`, web UI: a confirm-gated "Reset all-time
  leaderboard…" link) wipes only `commander_ratings` — past sessions
  and their own results are untouched, so session history/resume/
  results still work exactly as before a reset. Confirmation lives
  client-side (CLI prompt, browser `confirm()`); the API endpoint
  itself has no confirmation step, consistent with this app having no
  auth to gate a "some day" separate confirmation UI behind anyway.
- **Static assets served `Cache-Control: no-cache`** (`web/app.py`'s
  `NoCacheStaticFiles`, also applied to `/`'s `index.html` response):
  FastAPI's default `StaticFiles` sends no explicit `Cache-Control`, so
  browsers fall back to their own heuristic caching -- mobile browsers
  hold onto a cached `app.js` far more stubbornly than a desktop tab
  with dev tools open. That could pair a freshly fetched `index.html`
  (new button markup renders) with a stale cached `app.js` (that
  markup's click handlers don't exist yet) right after a deploy --
  exactly the "button's there but tapping it does nothing" report that
  prompted this. `no-cache` still allows cheap ETag/Last-Modified
  conditional GETs (304s), it just forces the revalidation check
  instead of trusting a browser's own freshness heuristic.
- **No auth / no multi-user support yet** — deliberate, not
  forgotten. `GET /api/sessions` and the leaderboard currently return
  global state with no per-user scoping; fine for a single-user or
  personal-link deployment, but two simultaneous strangers would
  share one global session list. Real accounts (auth, `/api/sessions`
  scoped to the logged-in user, a user column on `sessions.db`) are
  the planned fix once this needs to support more than one person —
  no longer blocked on moving off local SQLite first, since
  `sessions.db` can already live on Turso.

## Roadmap

Reorganized 2026-07-19 around a real strategy conversation (previously
a flat "Feature roadmap" + "Not yet started" list that had grown
organically pass by pass) into four tiers: harden what exists, the
agreed next big goal, and an explicit someday backlog. Pull items from
here one at a time the same way every feature in this project has been
built so far — this is a backlog, not a schedule.

### 1. Harden before expanding

Not new features — tightening what's already shipped, per the
"good working product first" direction above:

- Trim/verify `themes.py::THEME_SLUGS` against EDHREC's real tag list
  (currently a curated guess; `update-data` skips 404s gracefully, but
  the list itself is noisy and worth correcting).
- Revisit Elo K-factor/round-count constants (`elo.py`) once there's
  been enough real usage to observe — currently hand-picked priors.
- A due-diligence pass confirming the fast-growing recent surface area
  (custom lists, the 32-deck challenge tracker, undo, bracket mode) all
  still behave correctly together — not a known bug, just worth
  checking before piling on more.

### 2. Next: Personalization

The agreed next big goal — builds on data/patterns already in place,
no new infrastructure (auth, sharing links) required:

- **Salt-score filter + theme-filter UI decision**: `PoolFilters` gains
  `max_salt`/`min_salt` (mirrors `max_price` exactly, including the
  permissive-on-missing-data posture). Separately, decide whether/how
  to re-enable the web UI's theme filter now that `GET /api/themes`
  reflects real per-commander tags instead of the old shallow list.
- **Saved filter presets**: small new `sessions.db` table (name ->
  serialized `PoolFilters`), a "Save this filter" action and a preset
  picker on the filter screen.
- **Favorites/collection tracking**: new table (commander name ->
  owned/wishlist flag), surfaced as a toggle on results/leaderboard
  rows and the lightbox. Pairs naturally with the 32-deck challenge
  tracker (mark a combo's chosen commander "owned" once the physical
  deck exists) without either feature needing to know about the
  other's schema.

### 3. Someday (recorded, not scheduled)

- **Real multi-user accounts** — the genuine long-term direction per
  this conversation, not a maybe, just deliberately after "harden" and
  "personalization." Comes with per-user session/leaderboard scoping
  (`sessions.db` already lives on Turso, so no longer blocked on moving
  off local SQLite first).
- **Social/competitive**: shareable results/leaderboard links, a
  champion share card, group/seasonal brackets (the last explicitly
  waits on multi-user).
- **Richer detail-page data**: the `similar` commanders list, and top
  EDHREC-ranked synergy nonland cards as a "starter list" once a
  commander's chosen — genuinely interesting, flagged as "maybe more
  later," not scheduled.
- **`commander-synergy` cross-link** — on hold; that sibling project
  isn't in a state worth linking to right now, revisit later.
- **AI "why this commander" blurb** — large. Needs a live LLM API call:
  an API key configured on the deployed service, and a real cost/latency
  tradeoff to think through before committing to it.
- **Session history across visits** (which commanders have already
  been shown/picked/rejected before, so repeat sessions can exclude
  recent picks).
- **Backfilling the all-time leaderboard** from pre-leaderboard-feature
  session history: the ~65 local sessions played before
  `commander_ratings` existed have their full `comparisons` history
  (every winner/loser pair with a timestamp) but no reconstructed
  rating — could be replayed through the Elo math to backfill, but
  deliberately skipped when Turso was set up (started that leaderboard
  fresh instead, by request) — the local history remains available if
  this is revisited later.
- **Provisional/games_played-based K-factor taper** (chess-style:
  bigger rating swings for a commander's first few games system-wide,
  smaller once it has more history) — considered while designing
  bracket mode's K-factor, but scoped out as orthogonal to that
  specific feature. Would apply to duel mode too, not just bracket.

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
