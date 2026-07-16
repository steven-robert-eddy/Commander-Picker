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
  - `target_round_count(pool_size)`: `n * log2(n)` heuristic, a
    **suggestion** surfaced to the user (printed mid-session), not a
    hard cutoff — sessions stay active and keep offering pairings past
    it until the user explicitly finishes.
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

## Phase 4 — Web UI (not started)

- FastAPI + plain HTML/JS, local-only to start, no build step — same
  proven pattern as `commander-synergy`'s Phase 4, chosen independently
  here for the same reasons (fast to build, no frontend tooling
  overhead) even though the two projects don't share code.
- Screens:
  1. **Filter** — color identity picker, archetype/theme checkboxes,
     deck-count slider (default ceiling ~10k), start session.
  2. **Swipe/compare** — two commander cards side by side (image, name,
     deck count, themes), click (or arrow keys) to pick a winner;
     progress indicator (round N of ~M); "I'm done" to end early.
  3. **Results** — ranked shortlist with ratings, links out to EDHREC
     page per commander.
- API: `POST /api/sessions` (filters → new session + first pairing),
  `POST /api/sessions/{id}/pick` (record a pick → next pairing or
  final results), `GET /api/sessions/{id}` (resume/inspect).

## Phase 5 — Stretch (not started)

- Card images sourced from Scryfall (EDHREC pages link card names, not
  always hotlinkable images) — small Scryfall lookup, not a full bulk
  import.
- Session history across visits (which commanders have already been
  shown/picked/rejected before, so repeat sessions can exclude recent
  picks).
- Cross-link to `commander-synergy`: once a commander is chosen, jump
  straight into that project's synergy finder for it.

## Known open questions / risks

- EDHREC JSON endpoint shapes are unconfirmed until this environment
  can actually reach edhrec.com — Phase 1 should build against
  captured/sample fixtures first (mirrors how `commander-synergy`
  handled the same class of sandbox network restriction) and get a
  live sanity-check pass once reachable.
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
