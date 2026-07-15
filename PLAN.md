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
  mapping for all 32 combos (colorless, 5 mono, 10 guilds, 10
  shards/wedges via standard Magic terminology — high confidence;
  4-color/5-color fall back to literal color letters — lower
  confidence, flagged in the module docstring).
- `commander_picker/themes.py`: curated list of ~18 EDHREC
  archetype/theme page slugs (tokens, aristocrats,
  plus-1-plus-1-counters, voltron, stax, ...).
- `commander_picker/edhrec_client.py`: fetches EDHREC's JSON pages —
  one per color-identity combo (`json.edhrec.com/pages/commanders/<slug>.json`)
  and one per theme (`.../pages/themes/<slug>.json`) — and caches them
  under `data/edhrec/` with a 24h freshness window (`--force` to
  bypass), same pattern as `commander-synergy`'s `bulk_data.py`. Polite
  client: identifying user agent, small delay between live fetches,
  cache-first.
- `commander_picker/db.py`: parses cached pages into
  `data/commanders.db` (SQLite) — `commanders` table (name,
  color_identity, num_decks, salt, edhrec_url, image_url/price
  columns present but unpopulated until Phase 5) plus a
  `commander_themes` junction table built by unioning which theme
  pages each commander name appeared on. Parsing logic
  (`_cardviews_from_page`, `_cardview_to_record`) is isolated in small
  functions specifically so it's a local fix once the real EDHREC
  shape is confirmed.
- CLI: `commander-picker update-data [--force] [--colors ...] [--themes ...]`,
  `list-colors`, `list-themes`.
- Tests: `tests/test_colors.py`, `test_edhrec_client.py` (mocked
  `requests`), `test_db.py` — all offline against hand-built fixtures
  in `tests/fixtures/`. 16/16 passing. Also manually verified the full
  `update-data` pipeline end-to-end against the fixtures (fetch →
  cache → SQLite → query).

**Known gap:** this dev sandbox's egress policy blocks edhrec.com (403
via the proxy — confirmed, same class of restriction the sibling
synergy project hit with Scryfall), so `update-data` has never
actually reached live EDHREC in this environment. The URL templates
and the assumed `container.json_dict.cardlists[].cardviews[]` response
shape (fields: `name`, `sanitized`, `url`, `label`, `num_decks`,
`salt`, `colors`) are a best-effort guess from public knowledge, not a
captured live response. Whoever runs this with real network access
should run `commander-picker update-data` once, sanity-check
`data/commanders.db` (row count, spot-check a few well-known
commanders' deck counts against edhrec.com directly), and fix up the
URL templates / parser in `db.py` if the real shape differs — the CLI
now fails cleanly with a clear error message rather than a raw
traceback if fetching breaks, so this should be easy to spot.

## Phase 2 — Filtering & candidate pools (not started)

- Query layer over `commanders.db`: filter by color identity (exact or
  subset), max/min deck count, one or more archetype tags, optional
  price ceiling.
- `build_pool(filters) -> list[Commander]` — the candidate set handed
  to the picker engine. Enforce a sane pool size (min/max) so the
  picker has enough signal without being unwieldy (e.g. 8–40
  candidates).
- CLI: `commander-picker pool --colors ... --max-decks 10000 --theme tokens`
  to preview a filtered pool before running a picker session.

## Phase 3 — Picker engine: Elo-style swipe/rank feed (not started)

- `commander_picker/picker.py`: maintain a rating per candidate in the
  pool (start all equal, e.g. 1000).
- Pairing: prefer comparing candidates with close current ratings
  (reduces wasted comparisons once ratings start to separate); early
  rounds can pair more randomly to get initial signal across the whole
  pool.
- Update ratings with a standard Elo formula after each pick (tune the
  K-factor; consider decaying it as more comparisons accumulate).
- Stopping condition: run a bounded number of rounds scaled to pool
  size (e.g. proportional to `n * log2(n)`) so the session has a
  predictable length, but let the user end early ("I'm done") or keep
  going past the suggested minimum if they want more separation.
- Persist session state (candidate pool, ratings, comparison history)
  so a session can be resumed later, not just held in memory —
  SQLite table keyed by session id.
- Output: full ranked shortlist at the end, not just the top pick —
  the point is narrowing down, and 2nd/3rd place are useful too.

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
