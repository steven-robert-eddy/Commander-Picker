# Commander Picker — Plan & Progress

Help the user decide which EDH/Commander deck to build next. Pulls
commander popularity/theme data from EDHREC, lets the user filter down
to a candidate pool (colors, archetype, "underbuilt" deck-count
ceiling), then runs a swipe-style head-to-head picker with Elo ratings
until a clear winner emerges.

Stack: Python, SQLite (local cache + queryable DB), EDHREC's JSON data
as the source. Standalone project — no dependency on the sibling
`commander-synergy` repo's package, though the two may link to each
other later (e.g. "find synergy for this pick" once a commander is
chosen).

## Concept recap

- **Data source**: EDHREC (https://edhrec.com) — deck counts per
  commander, color identity, and EDHREC's own archetype/theme tagging
  (Tokens, +1/+1 Counters, Aristocrats, Voltron, Group Hug, etc.), not
  Scryfall's oracle text.
- **Filtering**: color combo(s), max deck count (default configurable
  threshold, e.g. < 10,000 decks, to surface underbuilt commanders),
  archetype/theme.
- **Picker**: given a filtered candidate pool, run a swipe/rank feed —
  show two candidates at a time, user picks the one they'd rather
  build, ratings update (Elo-style), repeat until a stopping condition
  is met, surface the ranked shortlist (not just a single "winner").

## Phase 1 — EDHREC data ingestion ✅ done

- `commander_picker/colors.py`: color-identity ↔ EDHREC URL slug
  mapping for all 32 combos. **Verified 2026-07-16** against a live
  `.../pages/commanders/rakdos.json` response's `related_info` block,
  which lists every color-identity slug directly — including the
  four-color names, which turned out to be real Alara Nephilim
  nicknames (`yore-tiller`, `glint-eye`, `dune-brood`, `ink-treader`,
  `witch-maw`) and `five-color`, not the literal-letter guess this
  started with.
- `commander_picker/themes.py`: curated list of ~18 EDHREC
  archetype/theme page slugs (tokens, aristocrats,
  plus-1-plus-1-counters, voltron, stax, ...) — still unverified, see
  known gap below.
- `commander_picker/edhrec_client.py`: fetches EDHREC's JSON pages —
  one per color-identity combo (`json.edhrec.com/pages/commanders/<slug>.json`,
  **confirmed working live**) and one per theme (`.../pages/themes/<slug>.json`,
  **confirmed wrong** — 403s against real EDHREC, see known gap) —
  and caches them under `data/edhrec/` with a 24h freshness window
  (`--force` to bypass), same pattern as `commander-synergy`'s
  `bulk_data.py`. Polite client: identifying user agent, small delay
  between live fetches, cache-first.
- `commander_picker/db.py`: parses cached pages into
  `data/commanders.db` (SQLite) — `commanders` table (name,
  color_identity, num_decks, edhrec_url, salt/image_url/price columns
  present but unpopulated — salt isn't on this list endpoint at all,
  turns out; image_url/price deferred to Phase 5) plus a
  `commander_themes` junction table built by unioning which theme
  pages each commander name appeared on. **Verified 2026-07-16**
  against a live color-identity page: cardviews carry
  `name`/`sanitized`/`num_decks`/`url` but no per-card `colors` or
  `salt` field (color identity comes from the page itself, not a
  per-card field — fixed after the first live test caught it). Parsing
  logic (`_cardviews_from_page`, `_cardview_to_record`) stayed isolated
  in small functions, which is exactly what made this a quick fix
  instead of a rewrite.
- CLI: `commander-picker update-data [--force] [--colors ...] [--themes ...]`,
  `list-colors`, `list-themes`. Fails cleanly with a clear message
  (not a raw traceback) on fetch/DB errors.
- Tests: `tests/test_colors.py`, `test_edhrec_client.py` (mocked
  `requests`), `test_db.py` — all offline. `sample_color_page.json` is
  now a trimmed real captured response (was a hand-built guess before
  live verification); `sample_theme_page.json` is hand-assembled from
  a real captured `tags/tokens.json` response's `topcommanders` list
  (trimmed and with names swapped to overlap with the color fixture
  for merge testing), not itself a raw capture. 17/17 passing.

**Known gap (color pages): none — resolved.** Live-verified 2026-07-16
by running `update-data --colors rakdos` from an environment with real
network access (this dev sandbox still can't reach edhrec.com itself —
confirmed 403 via the proxy). `colors.py` and the color-page parsing
path in `db.py` are both confirmed correct against real data.

**Known gap (theme pages): none — resolved.** The `/pages/themes/...`
guess 403'd from EDHREC's own server (not the sandbox's proxy — the
color fetch on the same run succeeded first, ruling that out). Live
testing several candidate URLs found it: EDHREC calls these "tags"
internally, not "themes" — the correct pattern is
`https://json.edhrec.com/pages/tags/<slug>.json`. Response shape is
the same `container.json_dict.cardlists[].cardviews[]` nesting as
color pages, just with multiple cardlists per page (`topcommanders`,
`newcommanders` are the ones we want; `topcards`/`highsynergycards`/
`creatures`/etc. are non-commander cards synergistic with the theme,
which the existing by-exact-name matching in `db.py` already ignores
correctly with no code change needed). One quirk: a theme page's
`num_decks` per commander means "decks with this commander tagged
with this theme," a different, smaller number than the color page's
total — irrelevant to us since color pages stay the authoritative
source for deck counts and theme pages only contribute the tag
itself. `THEME_SLUGS` in `themes.py` is still an unverified curated
guess of *which* tag slugs exist (only `tokens` has been confirmed
live) — the URL *pattern* is now correct, but individual slugs beyond
`tokens` (aristocrats, voltron, stax, ...) haven't been spot-checked.
A full `update-data` run will just 404/403 per-slug on any that don't
exist and move on (each slug is fetched independently), so this isn't
blocking, but the theme list is worth trimming/correcting against
EDHREC's real tag list at some point.

Fixing this also surfaced and fixed a real bug: `fetch_all_pages` /
`load_commanders` used `color_slugs or all_slugs()` (and the theme
equivalent) to apply defaults, which silently treats an explicitly
passed empty list `[]` the same as `None` in Python — so "fetch/load
zero themes" was previously impossible to express, it always fell
back to the full default list. Both now check `is None` instead.
`fetch_all_pages` also no longer aborts the whole run on the first
bad slug — per-slug failures are collected and returned as a
`(results, failures)` tuple instead of raised, since a wrong theme
slug shouldn't lose already-fetched color pages. `commander-picker
update-data` prints color-page failures as warnings (unexpected —
those slugs are verified) and theme-page failures as an informational
note (expected — `THEME_SLUGS` is still a guess).

### Pagination ✅ done

A full live `update-data` run initially returned only 2,667 total
commanders, capped at exactly 100 per color combo for every popular
color — the first page of each color list only holds ~100 entries and
was silently dropping everything past that. In the real Rakdos data,
rank #100 was already down to 560 decks, meaning essentially every
genuinely obscure/underbuilt commander (the actual core premise of
this app) was missing. Root cause: each cardlist that has more results
carries a `more` field (a relative path to a continuation page) that
wasn't being followed.

Fixed in `edhrec_client.py` (`_paginate_cardlist`/`_paginate_page`,
called from `_fetch_page` before caching):

- Continuation pages have a **different shape** than the first page —
  flat `{"cardviews": [...], "is_paginated": bool, "more": "..."}`,
  not wrapped in `container.json_dict.cardlists` — verified live
  2026-07-16 against a real second Rakdos page before writing any
  code, rather than guessed.
- Follows the `more` chain per-cardlist, merging continuation
  cardviews into the original cardlist, until either a continuation
  page's lowest `num_decks` drops below `MIN_DECKS_FLOOR` (50) or
  `MAX_CONTINUATION_PAGES` (15) is hit — whichever comes first. This
  was a deliberate product decision (confirmed with the user, not
  assumed): chasing every single-digit-deck commander would mean
  dozens of requests per popular color and surface data not really
  useful for "pick something worth building." Cardlists that never
  had a `more` field to begin with (naturally short lists, e.g. niche
  4c/5c combos) are left untouched — no reason to throw away data that
  cost no extra request.
- The merged, final cached page is a fully self-contained normal page
  (no leftover `more`/`is_paginated` keys) — `db.py`'s parser needed
  zero changes, since pagination is resolved entirely before caching.
- Tests: `test_pagination_follows_more_chain_and_merges_cardviews`,
  `test_pagination_stops_below_deck_floor`,
  `test_pagination_stops_at_max_continuation_pages` in
  `test_edhrec_client.py`, all offline/mocked. Also manually verified
  end-to-end with a simulated 3-page chain (100 + 100 + 10 entries,
  third page all below the floor) — correctly merged 200 entries and
  dropped the sub-floor page entirely.

**Live-verified 2026-07-16**: user re-ran `update-data --force` with
this fix. Total commanders went from 2,667 → 3,797 (+42%), under-10k
population from 2,443 → 3,573, under-1k → 2,241. No color-page
failures. Matches the expected shape from the real Rakdos sample
(crossing the 50-deck floor around rank ~190, vs. the old 100-entry
cap) — pagination is working correctly against live data, not just
the offline tests.

## Phase 1 status: done, fully live-verified

Every piece of the ingestion pipeline — color-identity slugs, color
page parsing, theme/tag page URL + parsing, and pagination — has now
been confirmed against real EDHREC responses (not just guessed or
offline-tested), each time by asking the user to fetch/paste real
data before writing the fix rather than guessing blind. `data/commanders.db`
built from a full live run has 3,797 real commanders with correct
color identities, deck counts, and theme tags.

## Phase 2 — Filtering & candidate pools ✅ done

- `commander_picker/pool.py`: `build_pool(conn, filters, max_pool_size,
  min_pool_size, rng) -> list[Commander]`.
- `PoolFilters`: `colors` (e.g. `"BRG"`, `None` = no color filter),
  `color_mode` (`"subset"` — commander's identity must fit within
  `colors`, the useful default for "I want to stay in these colors";
  or `"exact"`), `max_decks` (default 10,000), `min_decks`, `themes`
  (tuple of theme slugs), `themes_mode` (`"any"`/OR or `"all"`/AND).
  `max_price` deliberately not a field yet — `price` is unpopulated
  (always `NULL`) until Phase 5, so a real filter would silently
  exclude every commander.
- Pool size is bounded: raises `PoolTooSmallError` below
  `min_pool_size` (default 4, so callers loosen filters instead of
  handing the picker an unusably small set) and **random-samples**
  down to `max_pool_size` (default 40) when there are more matches —
  not a truncation to the highest deck counts, since the whole point
  is variety across the "under 10k" range rather than always seeing
  the same top-of-range commanders. `rng` is injectable for
  deterministic tests.
- `Commander.themes` is always populated from `commander_themes`
  regardless of whether the caller filtered by theme — caught by a
  test that would otherwise have silently shipped with themes blanked
  out on every non-theme-filtered query (an over-eager "skip the join
  when no theme filter" optimization broke correctness; removed).
- CLI: `commander-picker pool --colors BRG --color-mode subset
  --max-decks 10000 --min-decks 0 --themes tokens,aristocrats
  --themes-mode any --pool-size 40 --min-pool-size 4` — prints the
  matching pool sorted by deck count, or a clear error if too few
  match.
- Tests: `tests/test_pool.py`, 12 cases against an in-memory SQLite DB
  built directly (not via EDHREC fixtures, for precise control over
  the color/deck-count/theme combinations under test) — color
  subset/exact, deck-count range, theme any/all, pool-too-small,
  random size-capping, and the themes-always-populated regression.
  Also manually verified the CLI end-to-end against a real
  fixture-built DB.

## Phase 3 — Picker engine: Elo-style swipe/rank feed ✅ done

- `commander_picker/elo.py`: pure rating math + pairing selection, no
  DB dependency (unit-testable in isolation, reused by `sessions.py`).
  - `expected_score`/`update_ratings`: standard Elo formula, all
    candidates start at rating 1000, `K_FACTOR=32`.
  - `target_round_count(pool_size)`: `n * log2(n)` heuristic. Originally
    a soft suggestion (sessions stayed active indefinitely past it) —
    **changed to a hard cutoff in Phase 5** after a user played 70
    rounds of a 15-commander session (target 59) with no sign it would
    ever stop; see Phase 5 below.
  - `choose_pairing`: early rounds (first third of target_rounds) pair
    uniformly at random across the whole pool for initial signal;
    later rounds sort by current rating and pair rating-adjacent
    neighbors, since close matchups are more discriminating once
    ratings separate. Prefers a pair not already compared.
  - **Bug caught by testing, not assumed away**: adjacency-only search
    can "false exhaust" on a small pool — if the one remaining fresh
    pair ends up non-adjacent in the current sorted order (e.g. the
    two extremes, with everything else already compared and sorted
    between them), the naive adjacency loop never finds it even though
    the pool isn't actually exhausted, and falls back to a repeat too
    early. Fixed with an exhaustive-scan-across-all-pairs fallback
    before accepting a genuine repeat. Verified with a 200-seed stress
    test (zero premature repeats) in addition to the unit test that
    caught it.
- `commander_picker/sessions.py`: persistence in a **separate**
  `data/sessions.db`, deliberately not `commanders.db` — the catalog
  DB is fully dropped and rebuilt on every `update-data` run, which
  would silently wipe in-progress/completed sessions if they shared a
  file.
  - Tables: `sessions` (id, status, target_rounds, rounds_completed,
    description), `candidates` (per-session commander + current
    rating), `comparisons` (full history — every winner/loser pair,
    not just current ratings, so past sessions can be reviewed later
    if needed).
  - `create_session`, `next_pairing`, `record_pick`, `finish_session`,
    `get_session`, `list_sessions`, `get_rankings` — sessions default
    to `active` and only become `complete` when the user explicitly
    finishes; pausing (closing the CLI) leaves a session `active` and
    resumable.
- CLI: `commander-picker play [pool filters]` starts a new session and
  runs an interactive terminal loop (pick 1/2, `f` to finish, `q` to
  pause); `commander-picker resume <id>` continues a paused session;
  `commander-picker sessions` lists all sessions; `commander-picker
  results <id>` shows the current/final ranking without playing.
- Tests: `tests/test_elo.py` (10 cases — Elo math, target round count,
  pairing freshness/fallback/late-phase behavior) and
  `tests/test_sessions.py` (10 cases — persistence, rating updates,
  pause/resume semantics, pairing exhaustion) — 20 new tests, all
  offline. Also manually verified the full interactive CLI loop
  end-to-end (play → pause → resume → finish → results) via piped
  stdin against a real fixture-built catalog DB.

## Phase 4 — Web UI ✅ done

- FastAPI + plain HTML/JS, local-only, no build step — same proven
  pattern as `commander-synergy`'s Phase 4, chosen independently here
  for the same reasons even though the two projects don't share code.
- Before building the real thing, published an **interactive Artifact
  preview** (client-side only, real EDHREC data from earlier in this
  build) so the project owner — on their phone, no terminal access —
  could actually try the duel mechanic and sign off on the visual
  direction before the FastAPI backend existed. That validated design
  (dark "table felt" ground, gold foil accent, mana-color pip badges,
  a serif/sans/mono type pairing) is what the real frontend below
  ports, now wired to the live backend instead of hardcoded data.
- `commander_picker/web/app.py`: JSON API —
  `GET /api/themes`, `POST /api/pool` (preview a filtered pool),
  `POST /api/sessions` (create + first pairing), `GET /api/sessions`
  (list), `GET /api/sessions/{id}` (info), `GET
  /api/sessions/{id}/pairing`, `POST /api/sessions/{id}/pick`, `POST
  /api/sessions/{id}/finish`, `GET /api/sessions/{id}/results`. 503 if
  `commanders.db` doesn't exist yet, 422 if a filter combo is too
  small, 404 for an unknown session — same "clean error, not a raw
  traceback" posture as the CLI.
- `commander_picker/web/static/`: `index.html` + `app.js` (thin
  fetch-based client — no local Elo/data duplication, the server is
  authoritative) + `style.css` (ported from the validated Artifact).
  Three screens: filter (color/theme chips, deck-count slider, live
  pool-size preview) → duel (two cards, tap to pick, foil-sweep
  transition, progress bar) → results (ranked ledger with rating
  deltas).
- CLI: `commander-picker serve [--host] [--port] [--reload]`, refuses
  to start with a clear error if `commanders.db` is missing.
- **Two real bugs caught by actually clicking through it in a
  browser**, not just API-testing in isolation:
  1. The live filter preview enabled "Start dueling" once ≥2
     candidates matched, but session creation actually requires ≥4
     (`pool.DEFAULT_MIN_POOL_SIZE`) — so a 2-3 match filter looked
     startable and then failed confusingly on click. Fixed by gating
     the button on the same threshold server-side enforces, with a
     proactive "need at least N, have M" message instead of a
     post-click failure.
  2. `db.connect()` and `sessions.connect()` both defaulted their
     `db_path` parameter directly to the module-level path constant
     (`= DB_PATH`) — a classic Python gotcha where the default binds
     at function-*definition* time, so monkeypatching the module
     constant in tests silently had no effect on calls that didn't
     pass `db_path` explicitly. `test_web.py`'s fixtures hit this
     immediately. Fixed both to a `None`-sentinel pattern.
- Tests: `tests/test_web.py`, 11 cases via FastAPI's `TestClient`
  against a fixture-built catalog — full session lifecycle (create →
  pick → finish → pairing returns null once complete), 422/404/503
  error paths, static file serving. Also manually verified via a real
  `uvicorn` run + Playwright screenshots at every screen (filter with
  a too-small pool showing the fix in action, an in-progress duel, the
  winner foil-sweep, and final results) — not just curl, an actual
  rendered browser check end to end.

## Phase 5 — Stretch (partially done)

### Card images ✅ done

Requested directly by the project owner after trying the real web UI
("show a picture of the cards being compared").

- `commander_picker/scryfall_client.py`: fetches Scryfall's
  `oracle_cards` bulk data (same two-request pattern as
  `edhrec_client.py` — GET the bulk-data index to find the current
  download URL, then GET that URL for the actual card file), caches to
  `data/scryfall/`, builds a `name -> art_crop image URL` lookup.
  **Unverified against live Scryfall** — this dev sandbox blocks
  `api.scryfall.com` same as it blocks edhrec.com — built from public
  API docs, same discipline as the rest of this project: verify once
  someone with real network access runs `update-data`.
- Handles EDHREC's Partner-pair naming ("A // B" combining two
  independent Scryfall cards, not a real Scryfall card name) by
  falling back to the first half's art when the combined name isn't
  found directly. True double-faced/transform cards already use "A //
  B" as their real Scryfall name too, so those match without the
  fallback.
- `db.py::build_database` takes an optional `image_lookup` and
  resolves each commander's `image_url` from it.
  `cli.py update-data` fetches Scryfall data by default (`--skip-images`
  to opt out), failing gracefully (warning, continue without images)
  rather than aborting the whole run if Scryfall is unreachable.
- **Had to retrofit `sessions.py`** — a session's `candidates` table
  copies fields from `pool.Commander` at session-creation time, and
  `image_url` was missing from that copy (and from `CandidateDetail`/
  `RankedCommander`), so images would never have reached the duel
  screen even with Scryfall data available. Added the column (with a
  migration for existing `sessions.db` files), threaded through
  `get_candidates`/`get_rankings`.
- Frontend: `.card-art` full-bleed banner image on each duel card,
  small `.rank-thumb` on the results ledger. Both use
  `onerror="this.remove()"` so a failed/dead image URL collapses
  cleanly back to the text-only layout instead of showing a
  broken-image icon with a big reserved blank box — caught by testing
  with intentionally-fake image URLs (EDHREC's own per-card `id` field
  looks like a UUID but isn't a Scryfall card ID; using it directly in
  a test fixture produced exactly the broken-image case this fallback
  needed to handle).
- **Switched from art-crop to the full card face** after feedback that
  a cropped illustration alone doesn't show what the card actually
  *is* (name, mana cost, text box). `scryfall_client._card_image_url`
  now prefers `image_uris.normal`/`large` over `art_crop` (kept only
  as a last-resort fallback). `.card-art`/`.rank-thumb` CSS switched
  from a wide banner crop (`aspect-ratio: 5/2`, `object-fit: cover`)
  to the real Magic card ratio (`63/88`) with `object-fit: contain` so
  the whole card shows undistorted rather than being cropped to fill a
  box shaped for a landscape illustration. Verified with an SVG
  data-URI placeholder at the correct ratio (real Scryfall images
  aren't reachable from this dev sandbox any more than EDHREC's are).
  **Note:** `image_url` is resolved once and stored in `commanders.db`
  at `update-data` time, not recomputed on the fly -- a database built
  under the old art-crop-preferring code keeps those URLs until
  `update-data` is run again. Told the user this explicitly after they
  reported "still no text" on a database that predated this fix.
- **Responsive duel layout**: side-by-side comparison at ≥720px
  viewport width (`.duel` switches `flex-direction: column` →
  `row`, `.medallion`'s overlap margin flips from vertical to
  horizontal, `main`'s max-width grows from 480px to 860px), stacked
  top/bottom below that breakpoint. Verified at 420px (stacked) and
  1100px (side-by-side, medallion centered between the two cards) via
  Playwright screenshots.

### UX pass ✅ done

Also requested after trying the real UI, same conversation:

- **Typed exact deck-count entry**: the max-decks control was
  slider-only, which felt imprecise for picking an exact ceiling. Now
  a synced range + number input — drag for coarse, type for exact,
  either updates the other. (Caught + fixed a display bug in this
  pass: the number input's native spin-button icon was clipping the
  last digit of 5-digit values, e.g. "10000" rendering as "1000" —
  widened the field.)
- **Editable duel pool size**: `pool_size` (previously hardcoded to 40
  in the frontend) is now a number input, bounded 4–200 both
  client-side and server-side (`pydantic.Field(ge=..., le=...)` on
  `FiltersBody`).
- **Total match count shown separately from the capped duel pool**:
  `pool.py` gained `count_matches()` (extracted from `build_pool` via
  a new `_filtered_candidates` helper) so the UI can show "N
  commanders match your filters" — the real uncapped total — distinct
  from "dueling with up to 40" — the sampled session size. Previously
  only the capped number was visible, which was ambiguous about
  whether a filter was actually broad or just aggressively sampled.

### Archetype filter hidden, color-match mode exposed ✅ done

Requested after trying the real UI with real data: EDHREC's tag pages
turned out to only expose a shallow (~30 commander) "top commanders"
list per archetype regardless of color filtering — a data-source
limitation, not a bug in our pagination (which only ever paginated
color pages deeply; theme pages' own commander lists are just short by
design on EDHREC's end). Not enough signal to filter on yet.

- Archetype/theme chips removed from `index.html` (commented out with
  the reasoning above) and `renderThemeChips()` no longer called from
  `app.js` — but left defined, and `pool.py`/`sessions.py`/the API/the
  CLI (`pool --themes`, `play --themes`) all still fully support theme
  filtering. Easy to bring the UI back if EDHREC's data improves or
  another source is added.
- **Color match mode** was already fully implemented server-side since
  Phase 2 (`PoolFilters.color_mode`: `"subset"` — any combo within the
  selected colors, e.g. picking B+R shows mono-B, mono-R, *and* BR —
  or `"exact"` — only the exact combo) but the web UI never exposed
  it, hardcoded to `"subset"`. Added a two-way segmented toggle
  ("Any combo within colors" / "Exact colors only"). Verified with a
  small custom fixture spanning mono-B, mono-R, BR, and BG commanders:
  subset mode with B+R selected correctly returns all 4 non-BG
  commanders; exact mode correctly narrows to just the 2 BR ones.

**Two real bugs found immediately by the user actually using exact
mode** (not caught in the verification above, since that testing never
tried "exact" with zero colors selected or a colorless commander):

1. With no colors selected, `allowed_colors` defaulted to the full
   WUBRG set as a stand-in for "no filter" — harmless in `subset` mode
   (every identity is trivially a subset of all 5 colors) but silently
   wrong in `exact` mode, where it meant "5-color commanders only."
   Reported as "exact mode with nothing selected shows 68" (the
   catalog's actual 5-color commander count). Fixed: `colors=None` now
   bypasses color filtering entirely regardless of mode, in
   `_filtered_candidates`.
2. Colorless commanders are stored as `color_identity=""`. In `exact`
   mode, `set("")` (empty set) never equals `{"C"}` (the UI's
   pseudo-color for Colorless), so selecting Colorless always returned
   0 — the bug as reported. Digging into it surfaced a second,
   unreported consequence of the same root cause: in `subset` mode, an
   empty set is a subset of *any* allowed set, so colorless commanders
   were silently leaking into every color selection regardless of
   whether "C" was ever picked. Fixed by normalizing an empty
   `color_identity` to `{"C"}` before comparing in
   `_color_identity_matches`, so both modes treat "C" consistently on
   both sides of the comparison.

Covered by 4 new tests in `test_pool.py` (exact+no-colors returns
everything; colorless only matches when "C" is explicitly selected in
exact mode; colorless doesn't leak into an unrelated subset selection;
colorless is included when "C" is explicitly added to a subset
selection). Also re-verified live via Playwright against the exact
repro the user described.

### Round count: suggestion → hard cutoff ✅ done

Reported: "I did 15 commanders and it didn't stop after the
recommended 59 rounds, I am up to 70 and it is not ending." This was
working exactly as originally designed (`target_rounds` was explicitly
a soft suggestion, Phase 3's own docstring said so) — but the design
itself was wrong. Asked the user directly whether they wanted a prompt
at the threshold, an automatic stop, or just a clearer "you can stop
now" cue; they chose automatic stop.

- `sessions.py` gained `_maybe_auto_finish`: checks whether
  `rounds_completed >= target_rounds` on an active session and calls
  `finish_session` if so. Called from **both** `next_pairing` (so a
  session already sitting past its target — like the one in the bug
  report, or any session created before this existed — self-heals the
  moment anything asks it for a pairing, not just after one more pick)
  and `record_pick` (finalizes at the exact pick that crosses the
  threshold).
- **Real gap this surfaced**: `record_pick` never checked session
  status before recording a pick — a stale client (a duel screen left
  open past auto-finish, e.g. a second tab) could still POST a pick
  for a round that no longer existed, and it would be silently
  accepted. Added a guard: `record_pick` now raises `SessionError` (→
  `400` over the API) if the session isn't `active`.
- **Real gap this surfaced in the web frontend**: `app.js`'s `pick()`
  handled a `null` pairing response (the shape auto-finish produces)
  by doing *nothing* — `if (pairing) renderPairing(pairing);` had no
  `else`. Before this change that branch was dead code (sessions never
  auto-completed), so it had never been exercised; auto-finish made it
  reachable immediately. Fixed: a `null` pairing now fetches and
  renders the final results screen instead of leaving the last duel
  frozen on screen with no next action.
- CLI (`_interactive_loop`) restructured to check session status at
  the top of each loop iteration and print "Finished!" with full
  rankings the moment the session is no longer active, rather than the
  old per-pick "you've reached the suggested count" message that
  didn't actually change anything. Dropped "suggested"/`~` wording
  throughout the CLI and web UI now that the count is exact, not an
  estimate.
- Tests: 3 new in `test_sessions.py` (auto-finish exactly at
  `target_rounds`; a session manually set past its target self-heals
  via `next_pairing` alone, no pick required; `record_pick` on an
  already-finished session raises), 1 new in `test_web.py` (drives a
  full session to its real `target_rounds` via the API, confirms the
  final pick's response is `null`, confirms a follow-up pick attempt
  gets `400`). Also re-verified live: CLI with 20 buffered picks
  against a target of 8 stops exactly at round 8 and cleanly ignores
  the extra buffered input; web UI via Playwright clicking through 15
  rounds against a target of 8 auto-transitions to the results screen
  after exactly 8 clicks.

### Multi-card commanders: show both halves / both faces ✅ done

Two-card commanders were only ever shown one image. `scryfall_client
.resolve_image_url` deliberately fell back to just the first half's
art for Partner-pair names like "A // B" (documented as a known
simplification at the time), and single-faced-only lookups meant a
transform/MDFC commander's back face was never fetched at all. User
asked for both cards on a Partner/Background pair, and both sides of
a double-faced commander.

`image_url: str | None` became `image_urls: list[str]` end to end
(`scryfall_client.py` → `db.py` → `pool.py` → `sessions.py` →
`web/app.py` (free via `asdict`) → `app.js`/`style.css`):

- `scryfall_client._card_face_image_urls(card)` returns one URL per
  Scryfall `card_faces` entry when each face carries its own
  `image_uris` (true transform/MDFC layouts — front and back are
  genuinely different images), or a single URL from the card's own
  top-level `image_uris` otherwise (plain cards, and layouts like
  split/adventure that share one whole-card image despite also having
  multiple `card_faces`).
- `build_image_lookup` is now name → list[str] (was name → str).
- `resolve_image_urls(commander_name, lookup)`: exact-name hits
  (covers true DFCs, whose own Scryfall name is already "A // B")
  return that card's face list as-is; a "A // B" EDHREC Partner/
  Background name with no exact Scryfall match looks up "A" and "B"
  independently and concatenates both halves' images, instead of the
  old first-half-only fallback.
- `commanders.db`'s `image_url TEXT` column became `image_urls TEXT`
  storing a JSON array (the table is fully rebuilt every
  `update-data` run, so no migration needed there). `sessions.db`'s
  `candidates.image_url` migrated to `candidates.image_urls` (JSON
  array) via the existing add-column migration pattern — since
  `sessions.db` persists across app upgrades unlike `commanders.db`,
  the migration also folds any legacy single `image_url` value into
  the new list column for old on-disk sessions, rather than silently
  dropping their art.
- Frontend: `cardInnerHTML` and `renderResults` in `app.js` render a
  `.card-art-group`/`.rank-thumb-group` of 1–2 images side by side
  instead of a single `<img>`; `style.css` gives the group flex
  layout with a hairline seam between two images and keeps each at
  the real 63:88 card aspect ratio.

Verified: `test_scryfall_client.py` covers per-face DFC extraction,
the split/adventure single-image case, and partner-pair
concatenation (including one-half-missing); `test_db.py` and
`test_sessions.py` cover the JSON round-trip and the legacy
single-column migration; a manual pipeline smoke test (fixture EDHREC
page with a Partner pair and a DFC commander → `build_database` →
`/api/pool` via `TestClient`) confirmed both commanders' `image_urls`
arrays came through the real API response with 2 entries each, in
the right order. CSS layout confirmed via a Playwright screenshot of
`.card-art-group` with two placeholder images (real Scryfall images
aren't reachable from this sandbox — same limitation as the original
Scryfall integration). Full suite: 96 passed.

### Duel layout follow-ups + results lightbox + real mana pips ✅ done

Three rounds of feedback on the multi-card work above, plus a
project-wide ask:

- **"if it is two cards lets shrink them ... side by side if enough
  room"**: `.card-art-group` went from a fixed vertical stack to
  `flex-wrap` with each `.card-art` at `flex: 1 1 150px` / `min-width:
  150px` — two images share a row and shrink together once the
  container is wide enough (no media query; responds to the card's
  actual rendered width), otherwise the second wraps below at full
  width.
- **User's screenshot: a 2-image Partner pair next to a 1-image
  commander in a real duel** showed the pair's images shrunk to half
  width each while the opponent's single image stayed full width —
  same total slot width for both sides made the 2-card side's art
  read as "tiny," not "two cards." First fix attempt force-stacked
  the 2-image side instead (equal per-image width, but a much taller
  button) — better but still not what was asked for.
- **"i think we want two full cards side by side"**: replaced the
  force-stack with proportional sizing instead — `renderPairing()` in
  `app.js` now sets `flexGrow` on each duel `card-btn` equal to its
  own image count (min 1), so a 2-image side's button is roughly
  twice as wide as a 1-image opponent's on the desktop row layout.
  Each image then lands at the same per-image size as the opponent's
  single image, genuinely side by side. Only affects the row layout;
  the mobile stacked layout gives every card-btn the full viewport
  width regardless of flex-grow, so nothing to unbalance there.
- **Results screen: bigger card view.** Added a lightbox
  (`#lightbox` in `index.html`, `openLightbox`/`closeLightbox` in
  `app.js`) — clicking a ranked commander with art (`.rank-row.has-
  art`, keyboard-accessible via `tabindex`/`role="button"`/Enter or
  Space) shows its card(s) at real size against a dark backdrop;
  closes via the ✕ button, clicking the backdrop, or Escape.
  `.lightbox` scrolls (`overflow-y: auto`) so a 2-image commander's
  second card isn't silently cropped on a short viewport. Also bumped
  the inline `rank-thumb` size (28×39 → 36×50) for a small default
  legibility improvement independent of the lightbox.
- **"dont use the circles with wubrg, actually use the color pip
  symbol"** (project-wide): `pipsHTML()` in `app.js` now renders each
  color as an `<img>` pointing at Scryfall's own mana symbol SVGs
  (`https://svgs.scryfall.io/card-symbols/{W,U,B,R,G,C}.svg`) — the
  actual sun/water-drop/skull/fireball/tree glyphs players recognize
  from the cards themselves — instead of a plain colored circle with
  a letter in it. Removed the now-unused `--mana-w`/`-u`/`-b`/`-r`/
  `-g`/`-c` CSS variables and the per-letter `.pip.*` background
  rules along with it. Loaded directly by the browser like Scryfall
  card art already is, so it works the same way once reachable on the
  user's machine.

Verified: full suite unaffected (96 passed, these are pure frontend
changes). Visually confirmed via Playwright screenshots: the
side-by-side vs. stacked wrap threshold at 230px/340px/520px card
widths; the proportional 2-vs-1 duel layout at desktop width (both
partner-pair images matching the opponent's single image in size);
and a standalone results-list + lightbox mockup (open, scroll to
reveal a cropped second image, close) using local placeholder art,
since `svgs.scryfall.io`/`cards.scryfall.io` aren't reachable from
this sandbox — real rendering to be confirmed on the user's machine
as with every other Scryfall-dependent piece of this project.

### First live verification of the multi-card/lightbox/mana-pip work ✅ done

The three items above (`image_urls` list, results lightbox, real mana
symbol SVGs) were all built and only offline/mock-verified in a
sandbox with no network access to edhrec.com or Scryfall. Ran a real
`update-data` and `serve` on a machine with real network access:

- **Real bug found and fixed**: EDHREC names a true double-faced/
  transform/MDFC commander after its **front face only** (e.g.
  `"Heliod, the Radiant Dawn"`, not Scryfall's actual card name
  `"Heliod, the Radiant Dawn // Heliod, the Warped Eclipse"`).
  `resolve_image_urls`'s exact-match path never found these, and its
  `" // " in commander_name` fallback never triggered either since
  the EDHREC name has no `//` in it — so every true transform/MDFC
  commander silently got zero images, the opposite of the Partner-pair
  case (which does contain `//` and already worked). Confirmed against
  a live-built `commanders.db`: 132 of 3,801 commanders had empty
  `image_urls`, 117 of which were true DFCs matchable by front-face
  name (`Heliod, the Radiant Dawn`, `Archangel Avacyn`, `King
  T'Challa`, `Katilda, Dawnhart Martyr`, etc.) — a large, systematic
  gap, not a handful of edge cases.
  - Fixed in `scryfall_client.py::build_image_lookup`: after indexing
    every card by its full Scryfall name, a second pass adds a
    front-face-name alias (`lookup.setdefault(face[0].name, urls)`)
    for every multi-face card, pointing at the same image list. Uses
    `setdefault` so it can never override a real card's own entry if a
    front-face name happens to collide with an unrelated card's full
    name (covered by a new test).
  - After the fix: 0 of 3,801 commanders have empty `image_urls`.
  - Tests: 2 new in `test_scryfall_client.py` (front-face alias
    resolves both images; alias never overrides a real card's own
    name).
- Visually verified via a live `uvicorn` run + Playwright, real
  network: mana symbol SVGs (`svgs.scryfall.io/card-symbols/*.svg`)
  load correctly in the filter chips (200 responses, rendered
  correctly, no console errors); a Partner-pair duel side renders two
  full, legible real card faces proportionally sized to match a
  single-card opponent; the results-screen lightbox opens two full-size
  legible cards for a Commander/Background pair with a working close
  button; a previously-broken DFC commander (`Heliod, the Radiant
  Dawn`) now shows its thumbnail on the results screen post-fix. No
  console errors, no failed network requests across the whole flow.

### Design polish pass (impeccable skill) ✅ done

Ran a full visual audit of all three screens (filter, duel, results +
lightbox) across mobile/tablet/desktop and both themes via Playwright
screenshots against a live `serve`, using the `impeccable` skill's
`polish` flow. Design system (dark table-felt ground, gold accent,
serif/sans/mono pairing, restrained product-register color use) was
already consistent and not touched -- confirmed rather than reworked.

- **Real bug found and fixed**: on a phone-width viewport, the results
  screen's `.rank-name` used `white-space: nowrap` + ellipsis, and the
  fixed-width thumbnail(s)/pips/rating columns left so little room for
  the name on a 390px screen that most commanders truncated to a
  handful of characters -- three different "Prava ..." entries all
  read identically, most rows lost their name past the first word.
  Confirmed via screenshot, not assumed. Desktop/tablet were
  unaffected (enough width that nothing truncated).
  - First fix attempt (let `.rank-name` wrap instead of truncating)
    fixed the ambiguity but surfaced a second issue on 2-image
    Partner-pair rows with a multi-color pip row: the leftover space
    beside the thumbnails+pips could be narrower than a single word,
    producing an ugly letter-by-letter wrap ("Sakashi" / "ma" / "of" /
    "a" / "Thousa" / "nd" on separate lines).
  - Real fix: `.rank-name-line` gained `flex-wrap: wrap` and
    `.rank-name` a `flex: 1 1 160px` basis, so the name drops to its
    own full-width line below the thumbnail(s)/pips whenever there
    isn't room beside them, instead of being squeezed into whatever
    narrow remainder is left. Verified: names now wrap at word
    boundaries only, every row legible, desktop/tablet layout
    unchanged (still one line, plenty of room).
- Everything else checked out clean: real card art renders correctly
  at all three breakpoints in both themes, the proportional 2-vs-1
  duel sizing and card-art-group seam render as designed, the lightbox
  opens correctly with proper contrast against its fixed dark backdrop
  in both themes, keyboard focus rings are clearly visible on chips/
  card-btns/buttons, and apparent "blank" thumbnails in one screenshot
  were confirmed via `naturalWidth` to be a `loading="lazy"` timing
  artifact of the screenshot tool, not a real missing-image bug (0
  commanders lack `image_urls` per the fix above).
- One pre-existing design-hook finding (`.progress-fill`'s `width`
  transition) reviewed and left as-is: a real progress bar filling is
  one of the few legitimate uses of a layout-property transition, and
  it predates this pass.
- Full suite still 98/98 passing (CSS-only change).

### Full visual identity redesign (impeccable skill) ✅ done

Requested directly: the previous dark-felt-and-gold theme reads as
generic "premium tool" scaffolding at this point ("every site nowadays
has the gold and black theme"). Reworked the palette from scratch via
`impeccable`'s color-strategy method rather than reskinning individual
values in isolation.

- **Mood**: a wizard's herbarium at dusk -- pressed leaves and inked
  marginalia under low library light, moss-glass jars on a dark shelf.
  Chosen over the old "casino card-table felt" metaphor specifically
  because it doesn't reach for gold/metallic accenting at all.
- **Two-hue brand system**, both in OKLCH, replacing the single gold
  accent: `--primary` (a deep moss green) marks *selected/chosen*
  state (active filter chips, the color-mode toggle); `--accent` (a
  burnt rust/terracotta) marks *actionable/emphasized* (the CTA
  button, focus rings, the winner glow, the #1 result). Distinct hues
  ~90° apart so the two roles stay visually separable even where
  lightness is close.
  - `--accent` (lighter, for text/borders against the dark ground) and
    `--accent-fill` (a deeper shade of the same hue, for solid button
    backgrounds under white text) are separate tokens -- one accent
    value can't simultaneously satisfy "readable as text on the page
    background" and "readable *under* white text as a button fill";
    trying to reuse a single value for both, first draft, failed the
    contrast check below.
  - Light theme's background moved off the classic warm cream/tan
    parchment (`#e4ddc9`, itself a recognized AI-default territory --
    same failure mode as the dark theme's gold, just the light-mode
    version of it) to a cool, barely-there sage-grey paper -- tinted
    per the "surface IS part of the brand" exception (an explicit
    herbarium/pressed-paper environment), not tinted "because warm
    feels nice."
  - Every token's contrast verified numerically (OKLCH -> linear sRGB
    -> WCAG contrast), not eyeballed: a Python script (see this
    session's scratch dir) computed real contrast ratios for every
    ink/accent/primary/good/bad pairing against its background in both
    themes before any CSS was written. First-draft accent value passed
    button-text contrast (7.2:1) but failed as plain text-on-background
    (2.96:1) -- caught by the script, fixed by splitting into
    `--accent`/`--accent-fill` above, not by picking values on
    instinct.
- **Winner treatment redesigned, not just recolored**: the old
  `@keyframes sweep` was a diagonal shine literally simulating gold
  foil catching light -- kept as CSS structure it would've stayed
  "the gold foil card game" regardless of hex values. Replaced with
  `@keyframes bloom`, a soft radial glow expanding from the card's
  center plus a gentle scale-in, reading as an inked stamp of approval
  instead of foil glare. Still transform/opacity only (no layout
  properties), still respects `prefers-reduced-motion`.
- **New small delight**: the results screen's #1 row gets a one-time
  `--accent-soft` podium tint -- a genuine one-off moment (the
  session's actual winner), not a repeated pattern down the list.
- CSS custom property names generalized alongside the value changes
  (`--felt`/`--felt-hi`/`--card`/`--card-border`/`--gold`/`--gold-soft`
  -> `--bg`/`--bg-alt`/`--surface`/`--border`/`--accent`/`--accent-soft`
  etc.) so the tokens no longer carry the old felt-table/foil-card
  metaphor in their names either.
- Verified via Playwright screenshots across mobile/tablet/desktop and
  both themes: filter chips, duel (single and multi-card sides),
  winner bloom, results podium tint, and lightbox all render correctly
  with the new palette; zero console errors/failed requests across a
  full play-through. Full suite still 98/98 passing (CSS-only change).

### Redesign follow-up: the first pass under-committed ✅ done

Reported directly: "the ui is worse" after the redesign above shipped.
Re-screenshotted with fresh eyes rather than assuming the *strategy*
(moving off gold/black) was the problem -- it wasn't; the *execution*
was too timid. Root cause: background/surface chroma was so low
(~0.017-0.021) it rendered as plain dark/light grey on a real screen,
so the only visible personality was one muted button -- objectively
less confident than the old high-contrast gold-on-black it replaced,
even though the color-cliché complaint was correctly addressed.

- Raised background/surface chroma substantially (dark bg
  0.017->0.03, surface 0.021->0.04; light bg 0.010->0.025) so the
  moss/ink mood actually reads as a deliberate deep-green (dark) /
  pale-sage (light) surface instead of neutral grey.
- Shifted primary's hue 132->145 (further from a muddy olive-brown,
  closer to a clean leaf green) and raised its chroma/lightness so the
  chip/segmented "selected" tint reads as fresh green rather than
  drab, and raised accent's chroma (0.15/0.19) and lightness for a
  punchier, more confident rust that actually commands attention the
  way the old gold did.
- Added real depth: `box-shadow` on `.panel` and `.card-btn` (soft
  drop shadow + a 1px inner top highlight) so panels read as raised
  material instead of a flat rectangle -- the flatness was part of
  why the first pass felt washed out, independent of the color values
  themselves.
- Every revised token re-verified with the same OKLCH->sRGB->WCAG
  contrast script as the first pass before shipping (all comfortably
  above the 4.5:1 floor, most well above); re-verified via Playwright
  across both themes/all breakpoints with zero console errors/failed
  requests. Full suite still 98/98 passing (CSS-only change).

### Not yet started

- Session history across visits (which commanders have already been
  shown/picked/rejected before, so repeat sessions can exclude recent
  picks).
- Cross-link to `commander-synergy`: once a commander is chosen, jump
  straight into that project's synergy finder for it.

## Known open questions / risks

- This dev sandbox still can't reach edhrec.com/Scryfall itself (403
  via the proxy) — every network-dependent piece (Phase 1's EDHREC
  ingestion, Phase 5's Scryfall images, this session's DFC image-lookup
  and UI redesign work) has to be built here first, then live-verified
  by whoever has real network access before trusting it. All of it
  *has* been live-verified at least once as of 2026-07-17 (see Phase 1
  and the "First live verification..." entry above) — this bullet is
  about the ongoing constraint on future changes, not an open gap in
  what's shipped so far.
- EDHREC's "num decks" figure is a moving target (updates continuously)
  — cache freshness window keeps this reasonably fresh without
  hammering the site on every session.
- Elo K-factor and round-count scaling are hand-picked priors to start,
  same as `commander-synergy`'s tag weights — expect to tune once
  there's real usage to observe (are sessions converging too fast/slow,
  does the shortlist feel right).

## Repo/branch notes

- Working repo: `steven-robert-eddy/commander-picker`.
- All work happens on branch `claude/mtg-commander-picker-w5iar6`.
- Sibling repos: `commander-synergy` (mechanical synergy finder given a
  commander name, Scryfall-based, fully built — see its own PLAN.md)
  and `commander-companion` (currently empty/unused).
