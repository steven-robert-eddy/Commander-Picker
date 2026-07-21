# Commander HQ — Plan & Progress

(Repo, remote, deploy URL, and CLI command are still `commander-picker`
— only the product-facing branding changed. See "Foundation pass" below.)

Help decide which EDH/Commander deck to build next, and track building
it out from there. Pulls commander popularity and archetype/theme data
from EDHREC, lets you filter down to a candidate pool (colors,
archetype, an "underbuilt" deck-count ceiling), then runs a swipe-style
head-to-head picker with Elo ratings to narrow the pool to a ranked
shortlist — playable from the terminal or a browser, with ratings that
persist and compound across sessions. Also tracks a 32-deck
color-identity challenge and a pod tracker (Elo for real games,
players, and decks) alongside the picker, from one home screen.

Stack: Python, SQLite (local cache + queryable DB), Turso (managed
libSQL) for session storage, EDHREC's JSON data as the source, Scryfall
for card art. Standalone project — no dependency on the sibling
`commander-synergy` repo's package; that project isn't in a state worth
linking to right now, so cross-linking is on hold (see "Optional/future" below).

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
- **Archetype/theme filter**: live in the web UI as of the
  "Harden before expanding" pass, once `THEME_SLUGS` went from an
  18-entry unverified guess to a 43-slug list confirmed live against
  EDHREC's own tag index. Collapsed behind a closed-by-default
  disclosure (`Archetype / theme (43) ▾`, `.filter-disclosure`) rather
  than always showing the full chip grid, since 43 chips was too much
  vertical space by default — same treatment later reused for the
  salt slider (below) once that existed too.
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
  no build step. A home screen (`#screen-home`) is the landing page,
  with the picker's filter UI one tap deeper behind "Pick a
  commander." Filter → duel → results → all-time leaderboard, with a
  lightbox for full-size card views. Same backend/data as the CLI.
- **Deployment**: a `Dockerfile` builds `commanders.db` during the
  image build itself (so the container ships fully self-contained),
  deployable to a free Render Web Service — see README's "Deploying"
  section for the runbook.
- **Foundation pass**: rebranded product-facing text to "Commander HQ"
  (repo/remote/deploy URL/CLI command unchanged — still
  `commander-picker`) and split the old monolithic `app.js` (1,227
  lines, one closure) into per-screen vanilla-JS modules under
  `web/static/js/` (`core.js`, `picker.js`, `leaderboard.js`,
  `sessions-list.js`, `challenge.js`, `home.js`, `init.js`), sharing
  state through a small `window.CP` namespace instead of one giant
  closure — no bundler, no build step, plain ordered `<script>` tags.
  Cross-module function calls always go through `CP.foo(...)` at the
  call site rather than being destructured at module-load time, since
  the modules' own `<script>` tags don't load in strict dependency
  order. Done to make room for the pod tracker (below) without the
  frontend growing past what one file can hold.
- **Pod tracker**: extends the picker's Elo idea to real multiplayer
  EDH games actually played at the table. Two separate rated entities,
  both in `sessions.db`: **players**
  (`players` table, freeform names, a row created implicitly the first
  time a name is used in a logged game, same posture as
  `commander_ratings`) and **decks** (`decks` table, a pre-registered
  catalog via `register_deck` — reused across many games, never
  hard-deleted, only archived/unarchived via `archive_deck`/
  `unarchive_deck`). A logged game (`log_pod_game`, backed by
  `pod_games`/`pod_game_participants`) needs >=2 participants and
  exactly one winner (EDH pods are almost always tracked casually as
  "who won," not a full ranked placement) and updates both ratings via
  a genuine N-player Elo generalization
  (`elo.multiplayer_expected_scores`/`update_multiplayer_ratings` --
  Bradley-Terry-Luce softmax across the whole field, zero-sum, applied
  once for players and once for decks) rather than naive pairwise
  decomposition, using `elo.MULTIPLAYER_K_FACTOR` (between the duel's
  and bracket's — see elo.py's comment for why). `delete_last_pod_game`
  mirrors `undo_last_pick`'s "only the most recent step" precedent, and
  is deliberately asymmetric: a player's row can vanish if that was
  their first-ever game (implicitly created, same as undoing a
  commander's first-ever pick), a deck's row never does (pre-
  registered independently of any game). Web UI: a new "Pod tracker"
  home card / `#screen-pod` / `pod.js` — log-a-game form, register-a-
  deck form (reuses the same commander search-as-you-type autocomplete
  the challenge tracker/custom-list already use), player and deck
  leaderboards, and a recent-games list with a delete button on the
  single most-recent entry only.
- **Backend split into `store.py`/`sessions.py`/`challenge.py`/`pods.py`**:
  proactive follow-up once the pod tracker landed — `sessions.py` had
  grown to house three unrelated concerns (picker sessions, the
  challenge tracker, the pod tracker) sharing one `sessions.db` file
  and one schema function, mirroring the same "one big file, several
  features" shape the Foundation pass already fixed on the frontend.
  `store.py` now owns the genuinely shared infrastructure (`connect`,
  `SessionError`, the schema/migrations, the Turso connection
  wrappers) — kept as one flat schema function rather than
  decentralized per-module hooks, since the latter would need circular
  imports for marginal benefit on a project this size. `sessions.py`
  re-exports `connect`/`SessionError`/etc. from `store.py`, so every
  existing external call site (`cli.py`, `web/app.py`'s picker
  endpoints) needed zero changes; `challenge.py`/`pods.py` are new,
  self-contained modules for their own concerns. Verified zero
  cross-concern coupling existed before the split (no challenge/pod
  function ever called a picker-only helper or vice versa), so this
  was a pure reorganization — same 250 tests, same behavior.
- **Min-decks filter**: `PoolFilters.min_decks` (default 100, CLI
  `--min-decks`, web slider paired with the existing max-decks one) —
  the obscurity floor to max-decks's underbuilt ceiling, excluding
  commanders with too little real deck-count signal to be a
  meaningful pick. Same permissive-on-missing-data posture as the
  other range filters.
- **UI shape-language revamp ("engraved plate")**: replaced the
  generic rounded-corner/pill-chip/ambient-drop-shadow look (the
  industry-default "AI app" skeleton) with a token-based inset-bevel
  system — `--groove`/`--emboss`/`--emboss-ghost`/`--deboss`/
  `--row-rule` custom properties applied consistently across panels,
  buttons, inputs, chips, and list rows, plus a restrained 4px
  `--card-radius` reserved for structural chrome (real card art and
  literal circles keep genuine rounding; nothing else does). Chosen
  after iterating through five distinct visual-direction comps.
- **Navigation clarity pass**: one persistent, accent-colored "← Home"
  link in the shared header (hidden only on the home screen itself),
  replacing five inconsistent per-screen "← Home" ghost-buttons and
  closing a real gap where the duel and results screens previously had
  no way back to Home at all. Undo/Finish-now on the duel screen moved
  off the same plain-text class used for the inert "tap a card to
  pick" hint next to them onto a distinct bordered `.action-btn`, so
  they read as clickable.
- **Scryfall Art Series bug fix + `refresh-candidates` command**: a
  real user-reported bug (a commander's card art showing a Kaldheim
  Art Series collectible instead of the real card) traced to
  Scryfall's bulk data including non-game objects that share a display
  name with the real card they depict — `scryfall_client.py` now
  filters out `layout in {art_series, token, double_faced_token,
  emblem, scheme, vanguard, planar}` before building either lookup.
  Separately: the all-time leaderboard/past sessions' own results
  don't read `commanders.db` live (a denormalized snapshot taken at
  session-creation time), so a catalog fix like this one never reached
  them on its own — `commander-picker refresh-candidates`
  (`favorites`-adjacent, new `sessions.refresh_candidate_metadata`)
  resyncs that existing snapshot from the current catalog on demand.
- **Salt-score filter + favorites/collection tracking**: both fully
  built — `PoolFilters.max_salt`/`min_salt` (CLI/API), and a new
  `commander_favorites` table/`favorites.py` module (owned/wishlist
  tracking per commander, independent of any session, with a `.fav-btn`
  toggle shared between rank rows and the lightbox) — then both hidden
  from the web UI shortly after shipping on direct user feedback, same
  `hidden`/`display:none` treatment as the standing price-filter
  precedent. Backend/CLI/API for both remain fully functional and
  tested; trivially reversible.
- **2026-07-21: paused here.** Harden-before-expanding and
  Personalization are substantially shipped; the app is in a good,
  stable place. See "Roadmap" below for what's left, all of it now
  explicitly optional/future rather than active work.

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
- **Scryfall's bulk `oracle_cards` file isn't only real cards**: it
  also includes non-game collectible objects (Art Series cards, tokens,
  emblems, etc.) that Scryfall names identically to the real card they
  depict/reference. `scryfall_client.py`'s `build_image_lookup`/
  `build_card_meta_lookup` key their lookups by plain card name, so
  without filtering, a same-named non-game entry can silently overwrite
  a real commander's image/mana-cost/type-line data depending purely on
  file order (found via a real bug report: "Cosima, God of the Voyage"
  was showing a Kaldheim Art Series card back instead of her real
  second face). `_is_game_card`/`_NON_GAME_LAYOUTS` filters out
  `layout in {"art_series", "token", "double_faced_token", "emblem",
  "scheme", "vanguard", "planar"}` before either lookup is built —
  none of these are ever legal commanders, so excluding them can't
  remove a real card's real data.
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
- **`candidates.color_identity`/`num_decks`/`edhrec_url`/`image_urls`
  are a display snapshot, not a live view**: written once at
  `create_session` time from whatever `commanders.db` said then, and
  `get_leaderboard`/`get_rankings` both read straight from that
  snapshot with no live dependency on `commanders.db` (a separate file
  entirely rebuilt by every `update-data` run). This surfaced as a
  real bug report: a Scryfall data-quality fix landed in
  `scryfall_client.py` (an Art Series card colliding with a real
  commander's name and overwriting its image), but the all-time
  leaderboard kept showing the old art even after `update-data`
  re-ran, because nothing refreshes the existing `candidates` rows.
  `sessions.refresh_candidate_metadata()` (CLI: `refresh-candidates`)
  is the fix: resyncs those four columns for every session that's ever
  included a given commander, from whatever `commanders.db` currently
  says, leaving `rating`/`rank`/`mana_cost`/`type_line`/`power_level`
  (genuine point-in-time history) untouched. Not run automatically —
  a deliberate, explicit step after `update-data`, same shape as
  `enrich-commanders`.
- **Static assets served `Cache-Control: no-store, no-cache,
  must-revalidate`, plus a `?v=` cache-buster on every `/static/`
  reference in `index.html`** (`web/app.py`'s `NoCacheStaticFiles`
  and `index()`): FastAPI's default `StaticFiles` sends no explicit
  `Cache-Control`, so browsers fall back to their own heuristic
  caching -- mobile Safari in particular held onto a cached JS module
  file stubbornly enough that a plain `no-cache` header (which only
  requires revalidation, not a full skip of the cache) wasn't
  reliably enough after the app.js-splitting pass: a user reported
  the *new* home screen rendering fine but tapping a card doing
  nothing on mobile, i.e. exactly a freshly fetched `index.html`
  paired with a stale cached `picker.js`/etc. (`window.CP.
  showFilterScreen()` silently throwing on an undefined function).
  `index()` now reads `index.html` and appends `?v=<process start
  time>` to every `src="/static/..."`/`href="/static/..."` at request
  time (`_BUILD_VERSION`, set once per server process, i.e. once per
  deploy) -- a genuinely different URL after every deploy defeats
  caching even against a browser that ignores `Cache-Control`
  entirely, on top of the stronger `no-store` header change.
- **No auth / no multi-user support yet** — deliberate, not
  forgotten. `GET /api/sessions` and the leaderboard currently return
  global state with no per-user scoping; fine for a single-user or
  personal-link deployment, but two simultaneous strangers would
  share one global session list. Real accounts (auth, `/api/sessions`
  scoped to the logged-in user, a user column on `sessions.db`) are
  the planned fix once this needs to support more than one person —
  no longer blocked on moving off local SQLite first, since
  `sessions.db` can already live on Turso.
- **Shape system ("engraved plate")**: `style.css` defines shared
  shadow/radius tokens (`--card-radius: 4px`, `--groove`, `--emboss`,
  `--emboss-ghost`, `--deboss`, `--row-rule`) used everywhere instead
  of the generic default look (8-16px rounded corners, pill-shaped
  chips/tags, ambient drop-shadow "elevation" on every panel). Panels
  use an inset four-side bevel (`--groove`) instead of a border or
  floating shadow; buttons use a two-line inset highlight/shadow
  (`--emboss`) to read as physically pressed rather than flat; inputs,
  selects, chips, and tags use a single inset shadow (`--deboss`) to
  read as a sunken slot; row separators between list items use
  `--row-rule` instead of `border-bottom`. Real elevation shadows are
  reserved for elements that are genuinely floating above content —
  `.autocomplete-dropdown` and the lightbox image — everything else in
  normal document flow uses the inset-bevel system instead. Rounded
  corners stay meaningful rather than decorative: only actual Magic
  card art (`.card-art`, `.rank-thumb`, lightbox images) and literal
  circles (`.medallion`, `.lightbox-close`) keep any real rounding: the
  new `--card-radius` on structural chrome is only 4px, just enough to
  soften a corner without reading as the generic "rounded-lg" default.

- **Deck-count filter is a range, not just a ceiling**: `max_decks`
  (default 10,000) excludes over-popular commanders so the picker
  stays focused on underbuilt ones; `min_decks` (default 100) excludes
  the opposite extreme — commanders with too few registered decks to
  be a meaningful signal (often a data artifact or a genuinely fringe
  pick). Both are plain `PoolFilters`/`FiltersBody` fields with the
  same "generous default, always adjustable" treatment; `None` means
  no floor/ceiling on either side.

- **One persistent Home control in the shared `<header>`, not
  per-screen back buttons**: `#header-home-btn` sits next to the phase
  label on every screen and is toggled by `core.js`'s `showScreen`
  (hidden only while already on `screen-home`) instead of each screen
  hand-rolling its own `← Home` ghost-button in an inconsistent
  position. This replaced five separate per-screen buttons — it also
  closed a real gap: `screen-duel` and `screen-results` previously had
  no way back to Home at all. `.action-btn` (Undo/Finish-now on the
  duel screen) reuses the same inset-ring technique as `.again-btn`/
  `.tag` instead of `.ghost-btn`, so real controls read as clickable
  buttons distinct from `.duel-hint`'s inert instructional text next
  to them.

## Roadmap

Reorganized 2026-07-19 around a real strategy conversation (previously
a flat "Feature roadmap" + "Not yet started" list that had grown
organically pass by pass) into four tiers: harden what exists, the
agreed next big goal, and an explicit someday backlog. Pull items from
here one at a time the same way every feature in this project has been
built so far — this is a backlog, not a schedule.

**2026-07-21: paused here.** The "harden" and "personalization" tiers
are substantially shipped and the app is in a good place. Everything
still open below — the Elo revisit, saved filter presets, and the
entire "Optional/future" tier — is explicitly **optional/future work,
not an active commitment**. Nothing here is next-up by default; treat this
section as ideas to pull from later if/when there's a reason to, not
a queue to keep working through.

### 1. Harden before expanding

Not new features — tightening what's already shipped, per the
"good working product first" direction above:

- ~~Trim/verify `themes.py::THEME_SLUGS` against EDHREC's real tag
  list~~ — done 2026-07-20 (an earlier attempt from this sandbox hit a
  blocked outbound proxy on `json.edhrec.com`; a later run had real
  network access). Every one of the original 18 slugs was verified
  live (all real, none dropped); 25 more genuine archetype tags were
  added by cross-checking against EDHREC's own tag index
  (`https://json.edhrec.com/pages/tags.json`, ~400 tags total),
  excluding tribal/creature-type and narrow single-keyword mechanic
  tags to keep the list focused on deck-building strategies. 43 slugs
  total now, all confirmed live.
- **(Optional/future)** Revisit Elo K-factor/round-count constants
  (`elo.py`) once there's been enough real usage to observe —
  currently hand-picked priors. **Still blocked**: no `sessions.db`
  with real accumulated games exists in this checkout (production data
  lives on Turso), so there's nothing to tune against yet. Revisit
  once real play volume exists.
- ~~A due-diligence pass confirming the fast-growing recent surface
  area (custom lists, the 32-deck challenge tracker, undo, bracket
  mode) all still behave correctly together~~ — **done**. Findings:
  custom-list bracket sizing and undo-vs-bracket-mode are already
  enforced server-side, not just hidden in the UI (`sessions.py`'s
  `create_session`/`undo_last_pick`, both re-checked via a raw API
  call bypassing the UI). Undoing the pick that finished a session
  un-finishing it (`sessions.py:395-398`) is documented, intentional
  behavior, not a bug — it just had no test coverage of the leaderboard
  reverting correctly, now covered
  (`test_undo_un_finishes_completed_session`). Custom-list sessions
  had never been played through to `/finish`/the leaderboard in any
  test even though the pick/rating code doesn't branch on session
  origin — now covered
  (`test_custom_duel_session_plays_through_to_leaderboard`,
  `test_custom_bracket_session_plays_through_to_leaderboard`). No
  application bug found. One gap intentionally left open: this repo
  has no JS test framework at all, so `picker.js`'s resume/bracket-mode
  undo-button-visibility logic (confirmed correct by code inspection,
  shared via `enterDuelScreen`) has nothing automated guarding it from
  a future regression — see "Known limitations."

### 2. Next: Personalization

The agreed next big goal — builds on data/patterns already in place,
no new infrastructure (auth, sharing links) required:

- ~~Salt-score filter + theme-filter UI decision~~ — **done**. Theme
  filter UI decision resolved earlier (re-enabled behind a collapsible
  disclosure, see the shape-language/UI-polish notes above). Salt:
  `PoolFilters` gained `max_salt`/`min_salt`, mirroring `max_price`
  exactly (including permissive-on-missing-data). Scope call: both
  are in the backend/CLI/API for parity with the min/max-decks
  precedent, but only a single "Max salt" slider was added to the web
  UI (`index.html`/`picker.js`) — a salt *floor* ("only show me spicy
  commanders") is a much more niche ask than the ceiling every other
  range filter in this app defaults to solving, so `min_salt` stays
  CLI/API-only for now, same position `max_price` is already in.
  **Update:** the "Max salt" slider itself was hidden from the web UI
  shortly after shipping, on direct user feedback that it wasn't
  landing well — same `hidden`-class treatment as `max_price`'s
  standing precedent (`index.html`'s `#salt-disclosure-btn`). Backend/
  CLI/API untouched and still fully functional; trivially reversible.
- **(Optional/future)** Saved filter presets: small new `sessions.db`
  table (name -> serialized `PoolFilters`), a "Save this filter"
  action and a preset picker on the filter screen.
- ~~Favorites/collection tracking~~ — **done**. `commander_favorites`
  (name -> "owned"/"wishlist", no row at all means neither) is a new,
  fully independent table (`favorites.py`, mirroring `challenge.py`'s
  shape) — `sessions.py`'s `RankedCommander`/`GlobalRanking` were never
  touched; `web/app.py`'s `_enrich_favorites` merges `favorite_status`
  into `results`/`finish`/`leaderboard` responses at the same app.py
  boundary `_enrich_challenge_entries` already uses, so the two
  features stay decoupled per this note's own original requirement. A
  single toggle (`.fav-btn`, `core.js`) cycles none → owned → wishlist
  → none, shared verbatim between rank rows and the lightbox. One real
  bug caught during this pass: `commander_name` must never be a URL
  *path* segment (`PUT /api/favorites/{commander_name}`) — several
  real commanders have "/" in their name (double-faced/Partner pairs
  like "Krark, the Thumbless // Vial Smasher the Fierce"), and
  Starlette's default path converter 404s on that even percent-encoded;
  fixed by moving it into the request body (`PUT`) / query string
  (`DELETE`) instead. No dedicated "My Collection" browse screen this
  pass — the roadmap note only called for the toggle itself.
  **Update:** the toggle itself was hidden from the web UI shortly
  after shipping, on direct user feedback that it wasn't landing
  well — `.fav-btn { display: none; }` in `style.css` is the only
  thing standing between this and being visible again; `core.js`
  still builds and wires it on every row exactly as before, and the
  full backend/API/tests are untouched.

### 3. Optional/future (recorded, not scheduled)

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

- `themes.py::THEME_SLUGS` (43 slugs) is verified live against EDHREC
  as of 2026-07-20 — see PLAN.md's "Harden before expanding" entry
  above. `update-data` still skips any slug that 404s (defense in
  depth against EDHREC renaming/removing a tag later), but the list
  itself is no longer an unverified guess.
- EDHREC's "num decks" figure is a moving target (updates
  continuously) — the cache freshness window keeps this reasonably
  fresh without hammering the site on every session.
- Elo K-factor and round-count scaling are hand-picked priors — worth
  tuning once there's real usage to observe.
- No JS test framework exists for the frontend (`commander_picker/web/
  static/js/*.js`) — correctness there (e.g. `picker.js`'s resume/
  bracket-mode undo/finish-button visibility logic) is only verified
  by code inspection and the standing manual Playwright pass, not by
  anything that runs automatically. Worth revisiting if frontend logic
  keeps growing in complexity.
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
