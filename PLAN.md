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

## Phase 1 — EDHREC data ingestion (not started)

- `commander_picker/edhrec_client.py`: fetch EDHREC's JSON data.
  EDHREC has no official public API, but its own frontend consumes
  JSON documents (commander lists per color combo, per theme/archetype
  pages, individual commander pages with average-deck data) served
  from a predictable JSON backend. Exact endpoint shapes need to be
  confirmed once this environment actually has network access to
  edhrec.com (same class of gap the sibling synergy project hit with
  Scryfall in its dev sandbox) — build the client against captured
  sample responses first, verify live once reachable.
- Cache raw JSON responses locally (`data/edhrec/*.json`) with a
  freshness window (e.g. 24h, `--force` to bypass), same pattern as
  `commander-synergy`'s `bulk_data.py`. Fetch by color-combo page and
  by theme/archetype page rather than one commander at a time, to
  minimize request count.
- Be a polite client: identifying user agent, no parallel hammering,
  cache-first. This is scraping a public site's data endpoints, not an
  official API — keep request volume low and cached.
- Load cached JSON into `data/commanders.db` (SQLite): one row per
  commander — name, color_identity, num_decks, themes (list), salt
  score, price, image_url, edhrec_url.
- CLI: `commander-picker update-data`.

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
