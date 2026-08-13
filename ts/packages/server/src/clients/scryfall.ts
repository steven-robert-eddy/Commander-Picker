/**
 * Fetch and cache Scryfall's oracle_cards bulk data, for card art/mana
 * cost/type line/price lookups. Ported from `commander_picker/scryfall_client.py`.
 *
 * Scryfall's bulk-data index no longer returns a plain-JSON `download_uri`
 * for oracle_cards -- only a gzip-compressed JSON Lines `jsonl_download_uri`,
 * one card object per line. `fetchOracleCards` decompresses/reassembles that
 * into a JSON array on disk; the old plain-JSON `download_uri` is still
 * accepted as a fallback in case Scryfall reintroduces it.
 */

import fs from "node:fs";
import zlib from "node:zlib";
import { ORACLE_CARDS_PATH, SCRYFALL_DIR, SCRYFALL_META_PATH, SCRYFALL_SETS_META_PATH, SCRYFALL_SETS_PATH } from "../paths.js";

const BULK_DATA_INDEX_URL = "https://api.scryfall.com/bulk-data";
const SETS_INDEX_URL = "https://api.scryfall.com/sets";

// Scryfall's own bulk data updates roughly daily.
export const DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60;

// set_type values that can plausibly print Commander-legal cards.
const RELEVANT_SET_TYPES = new Set(["expansion", "core", "commander", "masters", "draft_innovation"]);

// Non-game objects Scryfall includes in the same oracle_cards bulk file.
const NON_GAME_LAYOUTS = new Set(["art_series", "token", "double_faced_token", "emblem", "scheme", "vanguard", "planar"]);

function isGameCard(card: any): boolean {
  return !NON_GAME_LAYOUTS.has(card.layout);
}

const USER_AGENT = "commander-hq-ts/0.1 (+https://github.com/steven-robert-eddy/commander-picker)";
const REQUEST_HEADERS = { "User-Agent": USER_AGENT, Accept: "application/json;q=0.9,*/*;q=0.8" };

export class ScryfallFetchError extends Error {}

interface Meta {
  fetched_at?: number;
  download_uri?: string;
}

function readMeta(metaPath: string): Meta {
  if (!fs.existsSync(metaPath)) return {};
  try {
    return JSON.parse(fs.readFileSync(metaPath, "utf-8"));
  } catch {
    return {};
  }
}

function cacheIsFresh(dataPath: string, metaPath: string, maxAgeSeconds: number): boolean {
  if (!fs.existsSync(dataPath)) return false;
  const fetchedAt = readMeta(metaPath).fetched_at;
  if (fetchedAt === undefined) return false;
  return Date.now() / 1000 - fetchedAt < maxAgeSeconds;
}

/**
 * Ensure data/scryfall/oracle_cards.json exists and is fresh; return its path.
 * Two requests: GET the bulk-data index to find the current oracle_cards
 * download URL (these rotate), then GET that URL for the actual (large,
 * couple-hundred-MB) card data file.
 */
export async function fetchOracleCards(force = false, maxAgeSeconds = DEFAULT_MAX_AGE_SECONDS): Promise<string> {
  fs.mkdirSync(SCRYFALL_DIR, { recursive: true });

  if (!force && cacheIsFresh(ORACLE_CARDS_PATH, SCRYFALL_META_PATH, maxAgeSeconds)) {
    return ORACLE_CARDS_PATH;
  }

  let index: any;
  try {
    const indexResp = await fetch(BULK_DATA_INDEX_URL, { headers: REQUEST_HEADERS });
    if (!indexResp.ok) throw new Error(`HTTP ${indexResp.status}`);
    index = await indexResp.json();
  } catch (exc) {
    throw new ScryfallFetchError(`Failed to fetch Scryfall bulk-data index: ${(exc as Error).message}`);
  }

  const oracleEntry = (index.data ?? []).find((d: any) => d.type === "oracle_cards");
  if (!oracleEntry) {
    throw new ScryfallFetchError("No 'oracle_cards' entry in Scryfall's bulk-data index");
  }

  const downloadUri: string | undefined = oracleEntry.jsonl_download_uri || oracleEntry.download_uri;
  if (!downloadUri) {
    throw new ScryfallFetchError("Scryfall's oracle_cards bulk-data entry has no download URI");
  }

  let raw: Buffer;
  try {
    const cardsResp = await fetch(downloadUri, { headers: REQUEST_HEADERS });
    if (!cardsResp.ok) throw new Error(`HTTP ${cardsResp.status}`);
    raw = Buffer.from(await cardsResp.arrayBuffer());
  } catch (exc) {
    throw new ScryfallFetchError(`Failed to download Scryfall oracle_cards bulk file: ${(exc as Error).message}`);
  }

  if (downloadUri.endsWith(".gz")) {
    raw = zlib.gunzipSync(raw);
  }
  if (downloadUri.endsWith(".jsonl") || downloadUri.endsWith(".jsonl.gz")) {
    const cards = raw
      .toString("utf-8")
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => JSON.parse(line));
    fs.writeFileSync(ORACLE_CARDS_PATH, JSON.stringify(cards));
  } else {
    fs.writeFileSync(ORACLE_CARDS_PATH, raw);
  }
  fs.writeFileSync(SCRYFALL_META_PATH, JSON.stringify({ fetched_at: Date.now() / 1000, download_uri: downloadUri }));
  return ORACLE_CARDS_PATH;
}

export interface ScryfallSetSummary {
  code: string;
  name: string | null;
  set_type: string | null;
  released_at: string | null;
}

function setsCacheIsFresh(maxAgeSeconds: number): boolean {
  if (!fs.existsSync(SCRYFALL_SETS_PATH) || !fs.existsSync(SCRYFALL_SETS_META_PATH)) return false;
  let meta: Meta;
  try {
    meta = JSON.parse(fs.readFileSync(SCRYFALL_SETS_META_PATH, "utf-8"));
  } catch {
    return false;
  }
  if (meta.fetched_at === undefined) return false;
  return Date.now() / 1000 - meta.fetched_at < maxAgeSeconds;
}

/**
 * Fetch (or reuse cached) Scryfall's set index and return the relevant
 * subset -- a single small (~1MB) request, cheap enough to call before
 * any EDHREC set-page discovery crawl.
 */
export async function fetchScryfallSetIndex(force = false, maxAgeSeconds = DEFAULT_MAX_AGE_SECONDS): Promise<ScryfallSetSummary[]> {
  fs.mkdirSync(SCRYFALL_DIR, { recursive: true });

  let payload: any;
  if (!force && setsCacheIsFresh(maxAgeSeconds)) {
    payload = JSON.parse(fs.readFileSync(SCRYFALL_SETS_PATH, "utf-8"));
  } else {
    try {
      const resp = await fetch(SETS_INDEX_URL, { headers: REQUEST_HEADERS });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      payload = await resp.json();
    } catch (exc) {
      throw new ScryfallFetchError(`Failed to fetch Scryfall set index: ${(exc as Error).message}`);
    }
    fs.writeFileSync(SCRYFALL_SETS_PATH, JSON.stringify(payload));
    fs.writeFileSync(SCRYFALL_SETS_META_PATH, JSON.stringify({ fetched_at: Date.now() / 1000 }));
  }

  return (payload.data ?? [])
    .filter((entry: any) => RELEVANT_SET_TYPES.has(entry.set_type) && entry.code)
    .map((entry: any) => ({
      code: entry.code,
      name: entry.name ?? null,
      set_type: entry.set_type ?? null,
      released_at: entry.released_at ?? null,
    }));
}

function oneFaceImageUrl(imageUris: Record<string, string> | undefined | null): string | null {
  if (!imageUris) return null;
  return imageUris.normal || imageUris.large || imageUris.art_crop || null;
}

function cardFaceImageUrls(card: any): string[] {
  if (card.image_uris) {
    const url = oneFaceImageUrl(card.image_uris);
    return url ? [url] : [];
  }
  const urls: string[] = [];
  for (const face of card.card_faces ?? []) {
    const url = oneFaceImageUrl(face.image_uris);
    if (url) urls.push(url);
  }
  return urls;
}

/**
 * Card name -> ordered list of image URLs, for every card that has any.
 * Usually a single-element list; two elements for double-faced/transform
 * cards (front + back).
 */
export function buildImageLookup(oracleCardsPath: string = ORACLE_CARDS_PATH): Map<string, string[]> {
  if (!fs.existsSync(oracleCardsPath)) {
    throw new ScryfallFetchError(`${oracleCardsPath} does not exist yet. Run \`update-data\` first.`);
  }
  const cards = JSON.parse(fs.readFileSync(oracleCardsPath, "utf-8"));

  const lookup = new Map<string, string[]>();
  for (const card of cards) {
    if (!isGameCard(card)) continue;
    const urls = cardFaceImageUrls(card);
    if (urls.length > 0 && card.name) lookup.set(card.name, urls);
  }

  // EDHREC names true double-faced/transform/MDFC commanders after their
  // front face only -- add a front-face-name alias so resolveImageUrls's
  // exact-match path still finds them. Never overrides a real card's own
  // full name.
  for (const card of cards) {
    if (!isGameCard(card)) continue;
    const faces = card.card_faces ?? [];
    if (faces.length >= 2 && lookup.has(card.name)) {
      const frontName = faces[0]?.name;
      if (frontName && !lookup.has(frontName)) {
        lookup.set(frontName, lookup.get(card.name)!);
      }
    }
  }
  return lookup;
}

/**
 * Look up a commander's image(s), handling EDHREC's Partner-pair naming
 * ("A // B" where "A" and "B" are two separate Scryfall cards).
 */
export function resolveImageUrls(commanderName: string, lookup: Map<string, string[]>): string[] {
  if (lookup.has(commanderName)) return lookup.get(commanderName)!;
  if (commanderName.includes(" // ")) {
    const [firstHalf, secondHalf] = commanderName.split(" // ", 2);
    return [...(lookup.get(firstHalf) ?? []), ...(lookup.get(secondHalf) ?? [])];
  }
  return [];
}

export interface CardMeta {
  manaCost: string | null;
  typeLine: string | null;
  priceUsd: number | null;
}

function cardMeta(card: any): CardMeta {
  const faces = card.card_faces ?? [];
  // Transform/modal-DFC cards carry their real cost/type on the front
  // face rather than the top level (often blank for these).
  const manaCost = card.mana_cost || faces[0]?.mana_cost || null;
  const typeLine = card.type_line || faces[0]?.type_line || null;
  const prices = card.prices ?? {};
  const rawPrice = prices.usd || prices.usd_foil;
  return { manaCost: manaCost || null, typeLine: typeLine || null, priceUsd: rawPrice ? Number(rawPrice) : null };
}

/**
 * Card name -> CardMeta (mana cost, type line, USD price), for every card.
 * A separate pass over the same bulk file buildImageLookup already parses.
 */
export function buildCardMetaLookup(oracleCardsPath: string = ORACLE_CARDS_PATH): Map<string, CardMeta> {
  if (!fs.existsSync(oracleCardsPath)) {
    throw new ScryfallFetchError(`${oracleCardsPath} does not exist yet. Run \`update-data\` first.`);
  }
  const cards = JSON.parse(fs.readFileSync(oracleCardsPath, "utf-8"));

  const lookup = new Map<string, CardMeta>();
  for (const card of cards) {
    if (!isGameCard(card)) continue;
    if (card.name) lookup.set(card.name, cardMeta(card));
  }

  for (const card of cards) {
    if (!isGameCard(card)) continue;
    const faces = card.card_faces ?? [];
    if (faces.length >= 2 && lookup.has(card.name)) {
      const frontName = faces[0]?.name;
      if (frontName && !lookup.has(frontName)) {
        lookup.set(frontName, lookup.get(card.name)!);
      }
    }
  }
  return lookup;
}

const EMPTY_CARD_META: CardMeta = { manaCost: null, typeLine: null, priceUsd: null };

/**
 * Look up a commander's card details, handling EDHREC's Partner-pair
 * naming: an "A // B" pair that isn't a single Scryfall card gets both
 * halves' mana cost/type line concatenated and their prices summed (only
 * when both halves have a price).
 */
export function resolveCardMeta(commanderName: string, lookup: Map<string, CardMeta>): CardMeta {
  if (lookup.has(commanderName)) return lookup.get(commanderName)!;
  if (commanderName.includes(" // ")) {
    const [firstHalf, secondHalf] = commanderName.split(" // ", 2);
    const a = lookup.get(firstHalf);
    const b = lookup.get(secondHalf);
    if (!a && !b) return { ...EMPTY_CARD_META };
    const aa = a ?? EMPTY_CARD_META;
    const bb = b ?? EMPTY_CARD_META;
    const manaCost = [aa.manaCost, bb.manaCost].filter(Boolean).join(" // ") || null;
    const typeLine = [aa.typeLine, bb.typeLine].filter(Boolean).join(" // ") || null;
    const priceUsd = aa.priceUsd !== null && bb.priceUsd !== null ? aa.priceUsd + bb.priceUsd : null;
    return { manaCost, typeLine, priceUsd };
  }
  return { ...EMPTY_CARD_META };
}
