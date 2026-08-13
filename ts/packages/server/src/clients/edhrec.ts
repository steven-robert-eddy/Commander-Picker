/**
 * Fetch and cache EDHREC commander-list pages by color identity, theme,
 * set, and individual commander. Ported from `commander_picker/edhrec_client.py`.
 *
 * EDHREC has no official public API, but its own frontend consumes JSON
 * documents from `json.edhrec.com` that mirror what's rendered on each
 * commander-list page.
 */

import fs from "node:fs";
import path from "node:path";
import { colors, themes } from "@commander-hq/shared";
import { EDHREC_DIR, EDHREC_META_PATH } from "../paths.js";
import { fetchScryfallSetIndex } from "./scryfall.js";

const COLOR_PAGE_URL_TEMPLATE = "https://json.edhrec.com/pages/commanders/{slug}.json";
const THEME_PAGE_URL_TEMPLATE = "https://json.edhrec.com/pages/tags/{slug}.json";
const SET_PAGE_URL_TEMPLATE = "https://json.edhrec.com/pages/sets/{slug}.json";
const CONTINUATION_BASE_URL = "https://json.edhrec.com/pages/";

// Pagination stopping rules: whichever hits first.
const MIN_DECKS_FLOOR = 50;
const MAX_CONTINUATION_PAGES = 15;

const CACHE_PREFIXES: Record<PageKind, string> = {
  color: "color__",
  theme: "theme__",
  commander: "commander__",
  set: "set__",
};

export type PageKind = "color" | "theme" | "commander" | "set";

// EDHREC's own data updates roughly daily.
export const DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60;

const USER_AGENT = "commander-hq-ts/0.1 (+https://github.com/steven-robert-eddy/commander-picker)";
const REQUEST_HEADERS = { "User-Agent": USER_AGENT, Accept: "application/json;q=0.9,*/*;q=0.8" };

// Be a polite, cache-first client: small delay between page fetches when
// pulling multiple slugs in one run.
export const REQUEST_DELAY_SECONDS = 0.5;

export class EdhrecFetchError extends Error {}

export interface FetchResult {
  slug: string;
  kind: PageKind;
  path: string;
  fromCache: boolean;
}

export interface FetchFailure {
  slug: string;
  kind: PageKind;
  error: string;
}

function sleep(seconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

function cacheKey(kind: PageKind, slug: string): string {
  return `${CACHE_PREFIXES[kind]}${slug}`;
}

function pagePath(kind: PageKind, slug: string): string {
  return path.join(EDHREC_DIR, `${cacheKey(kind, slug)}.json`);
}

function urlFor(kind: PageKind, slug: string): string {
  // "commander" (an individual commander's detail page) shares the same
  // URL template as "color" -- EDHREC uses one route,
  // /pages/commanders/<slug>.json, for both a color-combo slug and a
  // specific commander's own slug.
  const template = kind === "theme" ? THEME_PAGE_URL_TEMPLATE : kind === "set" ? SET_PAGE_URL_TEMPLATE : COLOR_PAGE_URL_TEMPLATE;
  return template.replace("{slug}", slug);
}

interface MetaEntry {
  fetched_at: number;
  url: string;
}

function readMeta(): Record<string, MetaEntry> {
  if (!fs.existsSync(EDHREC_META_PATH)) return {};
  try {
    return JSON.parse(fs.readFileSync(EDHREC_META_PATH, "utf-8"));
  } catch {
    return {};
  }
}

function writeMeta(meta: Record<string, MetaEntry>): void {
  fs.writeFileSync(EDHREC_META_PATH, JSON.stringify(meta, null, 2));
}

function cacheIsFresh(key: string, filePath: string, meta: Record<string, MetaEntry>, maxAgeSeconds: number): boolean {
  if (!fs.existsSync(filePath)) return false;
  const fetchedAt = meta[key]?.fetched_at;
  if (fetchedAt === undefined) return false;
  return Date.now() / 1000 - fetchedAt < maxAgeSeconds;
}

async function getJson(url: string, errorContext: string): Promise<any> {
  let resp: Response;
  try {
    resp = await fetch(url, { headers: REQUEST_HEADERS });
  } catch (exc) {
    throw new EdhrecFetchError(`Failed to fetch ${errorContext} (${url}): ${(exc as Error).message}`);
  }
  if (!resp.ok) {
    throw new EdhrecFetchError(`Failed to fetch ${errorContext} (${url}): HTTP ${resp.status}`);
  }
  return resp.json();
}

async function paginateCardlist(cardlist: any): Promise<void> {
  cardlist.cardviews ??= [];
  let pagesFetched = 0;
  while (cardlist.more && pagesFetched < MAX_CONTINUATION_PAGES) {
    const morePath = cardlist.more;
    delete cardlist.more;
    const page = await getJson(`${CONTINUATION_BASE_URL}${morePath}`, "EDHREC continuation page");
    pagesFetched++;
    await sleep(REQUEST_DELAY_SECONDS);

    const pageCardviews = page.cardviews ?? [];
    cardlist.cardviews.push(...pageCardviews);

    const lowestNumDecks = pageCardviews.length > 0 ? (pageCardviews.at(-1).num_decks ?? 0) : 0;
    if (lowestNumDecks < MIN_DECKS_FLOOR) break;
    if (page.is_paginated && page.more) {
      cardlist.more = page.more;
    }
  }
  delete cardlist.is_paginated;
  cardlist.cardviews = cardlist.cardviews.filter((cv: any) => (cv.num_decks ?? 0) >= MIN_DECKS_FLOOR);
}

async function paginatePage(payload: any): Promise<void> {
  const cardlists = payload?.container?.json_dict?.cardlists ?? [];
  for (const cardlist of cardlists) {
    if (cardlist.more) {
      await paginateCardlist(cardlist);
    }
  }
}

async function fetchPage(kind: PageKind, slug: string, force: boolean, maxAgeSeconds: number): Promise<FetchResult> {
  fs.mkdirSync(EDHREC_DIR, { recursive: true });
  const meta = readMeta();
  const key = cacheKey(kind, slug);
  const filePath = pagePath(kind, slug);

  if (!force && cacheIsFresh(key, filePath, meta, maxAgeSeconds)) {
    return { slug, kind, path: filePath, fromCache: true };
  }

  const url = urlFor(kind, slug);
  const payload = await getJson(url, `EDHREC ${kind} page for ${JSON.stringify(slug)}`);
  await paginatePage(payload);

  fs.writeFileSync(filePath, JSON.stringify(payload));
  meta[key] = { fetched_at: Date.now() / 1000, url };
  writeMeta(meta);

  return { slug, kind, path: filePath, fromCache: false };
}

export function fetchColorPage(slug: string, force = false, maxAgeSeconds = DEFAULT_MAX_AGE_SECONDS) {
  return fetchPage("color", slug, force, maxAgeSeconds);
}

export function fetchThemePage(slug: string, force = false, maxAgeSeconds = DEFAULT_MAX_AGE_SECONDS) {
  return fetchPage("theme", slug, force, maxAgeSeconds);
}

export function fetchSetPage(slug: string, force = false, maxAgeSeconds = DEFAULT_MAX_AGE_SECONDS) {
  return fetchPage("set", slug, force, maxAgeSeconds);
}

export function fetchCommanderDetailPage(slug: string, force = false, maxAgeSeconds = DEFAULT_MAX_AGE_SECONDS) {
  return fetchPage("commander", slug, force, maxAgeSeconds);
}

export async function fetchAllPages(options: {
  force?: boolean;
  maxAgeSeconds?: number;
  colorSlugs?: string[] | null;
  themeSlugs?: string[] | null;
  setSlugs?: string[] | null;
}): Promise<[FetchResult[], FetchFailure[]]> {
  const { force = false, maxAgeSeconds = DEFAULT_MAX_AGE_SECONDS, colorSlugs, themeSlugs, setSlugs } = options;
  const results: FetchResult[] = [];
  const failures: FetchFailure[] = [];

  for (const slug of colorSlugs ?? colors.allSlugs()) {
    try {
      const result = await fetchColorPage(slug, force, maxAgeSeconds);
      results.push(result);
      if (!result.fromCache) await sleep(REQUEST_DELAY_SECONDS);
    } catch (exc) {
      failures.push({ slug, kind: "color", error: (exc as Error).message });
    }
  }
  for (const slug of themeSlugs ?? themes.THEME_SLUGS) {
    try {
      const result = await fetchThemePage(slug, force, maxAgeSeconds);
      results.push(result);
      if (!result.fromCache) await sleep(REQUEST_DELAY_SECONDS);
    } catch (exc) {
      failures.push({ slug, kind: "theme", error: (exc as Error).message });
    }
  }
  for (const slug of setSlugs ?? []) {
    try {
      const result = await fetchSetPage(slug, force, maxAgeSeconds);
      results.push(result);
      if (!result.fromCache) await sleep(REQUEST_DELAY_SECONDS);
    } catch (exc) {
      failures.push({ slug, kind: "set", error: (exc as Error).message });
    }
  }
  return [results, failures];
}

/**
 * Find which Scryfall set codes actually have an EDHREC set page. A few
 * hundred speculative requests -- meant to be run explicitly and
 * occasionally, not on every normal data refresh.
 */
export async function discoverSetSlugs(force = false): Promise<string[]> {
  const candidates = await fetchScryfallSetIndex(force);
  const found: string[] = [];
  for (const entry of candidates) {
    try {
      await fetchSetPage(entry.code, force);
    } catch {
      continue;
    }
    found.push(entry.code);
    await sleep(REQUEST_DELAY_SECONDS);
  }
  return found;
}

/** Whether a cached page exists on disk for this slug, regardless of freshness. */
export function pageExists(kind: PageKind, slug: string): boolean {
  return fs.existsSync(pagePath(kind, slug));
}

/** Every slug of this kind with a cached page on disk, regardless of freshness. */
export function cachedSlugs(kind: PageKind): string[] {
  const prefix = CACHE_PREFIXES[kind];
  if (!fs.existsSync(EDHREC_DIR)) return [];
  return fs
    .readdirSync(EDHREC_DIR)
    .filter((f) => f.startsWith(prefix) && f.endsWith(".json"))
    .map((f) => f.slice(prefix.length, -".json".length))
    .sort();
}

/** Load a cached page's JSON from disk. */
export function loadPage(kind: PageKind, slug: string): any {
  const filePath = pagePath(kind, slug);
  if (!fs.existsSync(filePath)) {
    throw new EdhrecFetchError(`No cached ${kind} page for ${JSON.stringify(slug)}. Run \`update-data\` first.`);
  }
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}
