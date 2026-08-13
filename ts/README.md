# Commander HQ (TypeScript)

A TypeScript rewrite of [Commander HQ](../README.md) — the same
EDH/Commander deck-picker product (EDHREC data ingestion, a filtered
candidate pool, an Elo-rated swipe/bracket picker, a 32-deck
color-identity challenge, a set-release challenge, and a multiplayer
pod tracker), reimplemented end-to-end as a Node/Express API and a
React frontend, living alongside the original Python/FastAPI app in
this same repo. The two are independent — separate data directories,
separate Docker images — nothing here touches `commander_picker/`.

## Status

Fully built and manually verified end-to-end: EDHREC/Scryfall data
ingestion, the full ~40-route HTTP API, and every one of the 9 web
screens (home, filter/setup, duel, results, leaderboard, sessions,
32-deck challenge, set challenge, pod tracker) — including a full duel
session with live Elo updates, a full bracket session from seeding
through champion, and pod-tracker game logging with dual player/deck
ratings.

Ported 1:1 from the Python implementation: the Elo rating math
(`K=32`/`16`/`24` for duel/bracket/multiplayer), the `n·log2(n)`
duel-round-count heuristic, recursive tournament bracket seeding, the
two-phase (random-then-adjacent) pairing heuristic, the color-identity
slug map, and all SQL schema/query logic. Covered by vitest unit tests
in `packages/shared` (algorithms) and `packages/server` (pool
filtering, session/bracket lifecycle).

Deliberately **not** ported: the Python app's interactive-terminal
duel/bracket picker and terminal `sessions`/`results`/`leaderboard`
commands — this version is web-only for actually playing a session;
the CLI here only covers data ingestion (see below). Also not
included yet: Turso/remote-DB support for `sessions.db` (the Python
app's dual local-sqlite/Turso backend) — noted as a clean future
addition, not needed for a fresh local-first deployment.

## Architecture

npm workspaces monorepo:

- **`packages/shared`** — pure TypeScript, no Node/DOM dependencies:
  domain types, the Elo/bracket algorithms (`elo.ts`), the
  color-identity slug map (`colors.ts`), and the curated theme-slug
  list (`themes.ts`). Used by both the server and the web client.
- **`packages/server`** — Express API + ingestion CLI, on
  `better-sqlite3`.
  - `db/catalog.ts` — `data/commanders.db` (3 tables, rebuilt from
    scratch on every `update-data` run).
  - `db/sessions.ts` — `data/sessions.db` (13 tables: sessions/
    brackets, both challenge trackers, pods, favorites).
  - `clients/edhrec.ts`, `clients/scryfall.ts` — the same fetch/cache/
    pagination logic as the Python clients, using Node's built-in
    `fetch`.
  - `domain/` — business logic (pool filtering, session lifecycle,
    both challenge trackers, pods, favorites), independent of HTTP.
  - `routes/` — the Express routes, one file per feature area.
  - `cli.ts` — `update-data`, `enrich-commanders`,
    `refresh-candidates`, `list-colors`, `list-themes`, `list-sets`,
    `serve`.
- **`packages/web`** — React + Vite + `react-router-dom` +
  `@tanstack/react-query`. One route per screen (a genuine improvement
  over the Python app's manual hidden-class screen switching — real,
  shareable, back-button-friendly URLs), same visual design
  (`styles/global.css` is a near-verbatim port of the Python app's
  `style.css`: same OKLCH theme tokens, same "engraved plate"
  component system) and interactions.

The API is a fresh wire format (camelCase JSON throughout, not a
byte-for-byte mirror of the Python app's snake_case FastAPI routes) —
reasonable since the TS frontend and backend are built together here,
with one deliberate correctness fix along the way: 32-deck/set
challenge commander removal and "choose" take the commander's name via
query param/request body instead of a URL path segment, since real
Partner-pair commander names contain `/` and can't round-trip through
a path segment (the Python app already applied this reasoning to its
`/api/favorites` endpoint, just not consistently to the challenge
trackers).

## Setup

Requires Node 20+.

```bash
cd ts
npm install
npm run build
```

## Fetching data

Same pipeline as the Python app, against the same EDHREC/Scryfall
sources, writing to `ts/data/` (a separate directory from the Python
app's `data/`, so the two never collide):

```bash
npm run cli update-data
```

Useful flags (all match the Python CLI's semantics):

- `--force` — bypass the 24h freshness cache.
- `--colors azorius,rakdos` / `--themes tokens,aristocrats` / `--sets
  sos` — restrict to specific slugs.
- `--discover-sets` — crawl Scryfall's set index for new EDHREC set
  pages (a few hundred speculative requests; run occasionally).
- `--skip-images` — skip the Scryfall card-art/meta fetch.

```bash
npm run cli enrich-commanders        # per-commander salt score, richer tags, power level
npm run cli refresh-candidates       # resync denormalized session/leaderboard display fields
npm run cli list-colors              # print all 32 color-identity slugs
npm run cli list-themes              # print all curated theme slugs
npm run cli list-sets                # print every set slug in the current catalog
```

## Running it

```bash
npm run cli serve --port 8000        # API + built web app on one origin
```

or for frontend development with hot reload (proxies `/api` to a
`serve` instance on port 8000, see `packages/web/vite.config.ts`):

```bash
npm run dev:server                   # tsx watch, port 8000
npm run dev:web                      # vite dev server, port 5173
```

## Testing

```bash
npm test
```

Runs vitest across `packages/shared` (Elo math, bracket seeding,
color-slug round-trips) and `packages/server` (pool filtering, session
and bracket lifecycle, undo semantics).

## Docker

```bash
docker build -t commander-hq-ts -f ts/Dockerfile ts
docker run -p 8000:8000 commander-hq-ts
```

Bakes a full `update-data --discover-sets` run into the image at build
time (same reasoning as the root `Dockerfile`: no persistent disk on a
typical free-tier host, so the catalog has to ship inside the image).
Needs real outbound network access to `edhrec.com`/`api.scryfall.com`
at build time.
