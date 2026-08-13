/**
 * Build a filtered candidate pool of commanders for the picker. Ported
 * from `commander_picker/pool.py`. Reads from `data/commanders.db`.
 */

import type Database from "better-sqlite3";
import {
  Commander,
  DEFAULT_MAX_DECKS,
  DEFAULT_MAX_POOL_SIZE,
  DEFAULT_MIN_DECKS,
  DEFAULT_MIN_POOL_SIZE,
  KnownSet,
  PoolFilters,
  SearchResult,
  TOP_THEMES_PER_COMMANDER,
} from "@commander-hq/shared";

export { DEFAULT_MAX_DECKS, DEFAULT_MIN_DECKS, DEFAULT_MIN_POOL_SIZE, DEFAULT_MAX_POOL_SIZE };

export class PoolTooSmallError extends Error {}
export class CommanderLookupError extends Error {}

/** Colorless commanders are stored as colorIdentity="" but the UI represents "Colorless" as pseudo-color "C". */
function colorIdentityMatches(colorIdentity: string, allowed: Set<string>, mode: "subset" | "exact"): boolean {
  const ci = colorIdentity ? new Set(colorIdentity.split("")) : new Set(["C"]);
  if (mode === "exact") {
    return ci.size === allowed.size && [...ci].every((c) => allowed.has(c));
  }
  return [...ci].every((c) => allowed.has(c));
}
export { colorIdentityMatches };

interface CommanderRow {
  name: string;
  color_identity: string;
  num_decks: number;
  edhrec_url: string | null;
  salt: number | null;
  image_urls: string;
  price: number | null;
  rank: number | null;
  mana_cost: string | null;
  type_line: string | null;
  power_level: number | null;
}

/** Each commander's theme tags, capped to its own top TOP_THEMES_PER_COMMANDER by deck count. */
function loadThemesByCommander(db: Database.Database): Map<string, Set<string>> {
  const rows = db
    .prepare(
      `
      SELECT commander_name, theme FROM (
          SELECT commander_name, theme,
                 ROW_NUMBER() OVER (
                     PARTITION BY commander_name ORDER BY num_decks DESC
                 ) AS rn
          FROM commander_themes
      )
      WHERE rn <= ?
      `
    )
    .all(TOP_THEMES_PER_COMMANDER) as { commander_name: string; theme: string }[];

  const map = new Map<string, Set<string>>();
  for (const row of rows) {
    if (!map.has(row.commander_name)) map.set(row.commander_name, new Set());
    map.get(row.commander_name)!.add(row.theme);
  }
  return map;
}

function loadCommandersBySet(db: Database.Database): Map<string, Set<string>> {
  const rows = db.prepare("SELECT commander_name, set_slug FROM commander_sets").all() as {
    commander_name: string;
    set_slug: string;
  }[];
  const map = new Map<string, Set<string>>();
  for (const row of rows) {
    if (!map.has(row.commander_name)) map.set(row.commander_name, new Set());
    map.get(row.commander_name)!.add(row.set_slug);
  }
  return map;
}

function rowToCommander(row: CommanderRow, themes: string[]): Commander {
  return {
    name: row.name,
    colorIdentity: row.color_identity,
    numDecks: row.num_decks,
    edhrecUrl: row.edhrec_url,
    themes,
    salt: row.salt,
    imageUrls: row.image_urls ? JSON.parse(row.image_urls) : [],
    price: row.price,
    rank: row.rank,
    manaCost: row.mana_cost,
    typeLine: row.type_line,
    powerLevel: row.power_level,
  };
}

/** Every commander matching filters, with no pool-size bounding applied. */
function filteredCandidates(db: Database.Database, filters: PoolFilters): Commander[] {
  const allowedColors = filters.colors ? new Set(filters.colors.toUpperCase().split("")) : null;
  const wantedThemes = new Set(filters.themes);
  const themesByCommander = loadThemesByCommander(db);
  const wantedSets = new Set(filters.sets);
  const setsByCommander = wantedSets.size > 0 ? loadCommandersBySet(db) : null;

  const rows = db
    .prepare(
      "SELECT name, color_identity, num_decks, edhrec_url, salt, image_urls, price, rank, mana_cost, type_line, power_level FROM commanders"
    )
    .all() as CommanderRow[];

  const candidates: Commander[] = [];
  for (const row of rows) {
    if (allowedColors !== null && !colorIdentityMatches(row.color_identity, allowedColors, filters.colorMode)) continue;
    if (filters.maxDecks !== null && filters.maxDecks !== undefined && row.num_decks > filters.maxDecks) continue;
    if (filters.minDecks !== null && filters.minDecks !== undefined && row.num_decks < filters.minDecks) continue;
    if (filters.maxPrice !== null && filters.maxPrice !== undefined && row.price !== null && row.price > filters.maxPrice) continue;
    if (filters.maxSalt !== null && filters.maxSalt !== undefined && row.salt !== null && row.salt > filters.maxSalt) continue;
    if (filters.minSalt !== null && filters.minSalt !== undefined && row.salt !== null && row.salt < filters.minSalt) continue;
    if (wantedSets.size > 0) {
      const commanderSets = setsByCommander!.get(row.name) ?? new Set<string>();
      if (![...wantedSets].some((s) => commanderSets.has(s))) continue;
    }

    const commanderThemes = themesByCommander.get(row.name) ?? new Set<string>();
    if (wantedThemes.size > 0) {
      const matches =
        filters.themesMode === "all"
          ? [...wantedThemes].every((t) => commanderThemes.has(t))
          : [...wantedThemes].some((t) => commanderThemes.has(t));
      if (!matches) continue;
    }

    candidates.push(rowToCommander(row, [...commanderThemes].sort()));
  }
  return candidates;
}

/** Every distinct theme tag actually stored in commander_themes. */
export function listKnownThemes(db: Database.Database): string[] {
  const rows = db.prepare("SELECT DISTINCT theme FROM commander_themes ORDER BY theme").all() as { theme: string }[];
  return rows.map((r) => r.theme);
}

/** Every distinct set (slug + human-readable name) actually stored in commander_sets. */
export function listKnownSets(db: Database.Database): KnownSet[] {
  const rows = db.prepare("SELECT DISTINCT set_slug, set_name FROM commander_sets ORDER BY set_name").all() as {
    set_slug: string;
    set_name: string;
  }[];
  return rows.map((r) => ({ slug: r.set_slug, name: r.set_name }));
}

/** Total commanders matching filters, before pool-size bounding -- for UI live-preview use. */
export function countMatches(db: Database.Database, filters: PoolFilters): number {
  return filteredCandidates(db, filters).length;
}

function shuffleSample<T>(items: T[], n: number): T[] {
  // Fisher-Yates partial shuffle, matching Python random.sample's
  // "n distinct elements, uniformly at random" semantics.
  const pool = [...items];
  for (let i = 0; i < n; i++) {
    const j = i + Math.floor(Math.random() * (pool.length - i));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  return pool.slice(0, n);
}

/**
 * Filter commanders.db down to a bounded candidate pool. Throws
 * PoolTooSmallError if the filtered set has fewer than minPoolSize
 * candidates. When the filtered set exceeds maxPoolSize, a random sample
 * is taken rather than truncating, for variety.
 */
export function buildPool(
  db: Database.Database,
  filters: PoolFilters,
  maxPoolSize: number = DEFAULT_MAX_POOL_SIZE,
  minPoolSize: number = DEFAULT_MIN_POOL_SIZE
): Commander[] {
  let candidates = filteredCandidates(db, filters);

  if (candidates.length < minPoolSize) {
    throw new PoolTooSmallError(
      `Only ${candidates.length} commander(s) match these filters (need at least ${minPoolSize}). Try loosening colors/deck-count/themes.`
    );
  }

  if (candidates.length > maxPoolSize) {
    candidates = shuffleSample(candidates, maxPoolSize);
  }

  return candidates;
}

/** Lightweight name search for the custom-list autocomplete. */
export function searchCommanders(db: Database.Database, query: string, limit = 20): SearchResult[] {
  const like = `%${query}%`;
  const rows = db
    .prepare("SELECT name, color_identity, num_decks FROM commanders WHERE name LIKE ? ORDER BY num_decks DESC LIMIT ?")
    .all(like, limit) as { name: string; color_identity: string; num_decks: number }[];
  return rows.map((r) => ({ name: r.name, colorIdentity: r.color_identity, numDecks: r.num_decks }));
}

/** Name search scoped to one set's own commander_sets membership. */
export function searchCommandersInSet(db: Database.Database, setSlug: string, query: string, limit = 20): SearchResult[] {
  const like = `%${query}%`;
  const rows = db
    .prepare(
      `SELECT c.name, c.color_identity, c.num_decks FROM commanders c
       JOIN commander_sets cs ON cs.commander_name = c.name
       WHERE cs.set_slug = ? AND c.name LIKE ? ORDER BY c.num_decks DESC LIMIT ?`
    )
    .all(setSlug, like, limit) as { name: string; color_identity: string; num_decks: number }[];
  return rows.map((r) => ({ name: r.name, colorIdentity: r.color_identity, numDecks: r.num_decks }));
}

/** Bulk lookup of image_urls/color_identity by exact commander name. */
export function commanderImagesByName(
  db: Database.Database,
  names: string[]
): Map<string, { imageUrls: string[]; colorIdentity: string }> {
  const result = new Map<string, { imageUrls: string[]; colorIdentity: string }>();
  if (names.length === 0) return result;
  const placeholders = names.map(() => "?").join(",");
  const rows = db
    .prepare(`SELECT name, image_urls, color_identity FROM commanders WHERE name IN (${placeholders})`)
    .all(...names) as { name: string; image_urls: string; color_identity: string }[];
  for (const row of rows) {
    result.set(row.name, { imageUrls: row.image_urls ? JSON.parse(row.image_urls) : [], colorIdentity: row.color_identity });
  }
  return result;
}

/**
 * Exact-name lookup for custom lists -- bypasses filtering entirely.
 * Preserves the caller's order and raises CommanderLookupError on any
 * unknown name or duplicate.
 */
export function commandersByNames(db: Database.Database, names: string[]): Commander[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const name of names) {
    if (seen.has(name)) duplicates.add(name);
    seen.add(name);
  }
  if (duplicates.size > 0) {
    throw new CommanderLookupError(`Duplicate commander name(s): ${[...duplicates].sort().join(", ")}`);
  }

  const themesByCommander = loadThemesByCommander(db);
  const rows = db
    .prepare(
      "SELECT name, color_identity, num_decks, edhrec_url, salt, image_urls, price, rank, mana_cost, type_line, power_level FROM commanders"
    )
    .all() as CommanderRow[];
  const rowsByName = new Map(rows.map((r) => [r.name, r]));

  const candidates: Commander[] = [];
  const missing: string[] = [];
  for (const name of names) {
    const row = rowsByName.get(name);
    if (!row) {
      missing.push(name);
      continue;
    }
    candidates.push(rowToCommander(row, [...(themesByCommander.get(row.name) ?? new Set<string>())].sort()));
  }
  if (missing.length > 0) {
    throw new CommanderLookupError(`Unknown commander name(s): ${missing.join(", ")}`);
  }
  return candidates;
}

/** Human-readable summary of a PoolFilters, used as a session's stored description. */
export function describeFilters(filters: PoolFilters): string {
  const parts: string[] = [];
  if (filters.colors) parts.push(`colors=${filters.colors} (${filters.colorMode})`);
  if (filters.maxDecks !== null && filters.maxDecks !== undefined) parts.push(`max_decks=${filters.maxDecks}`);
  if (filters.minDecks !== null && filters.minDecks !== undefined) parts.push(`min_decks=${filters.minDecks}`);
  if (filters.maxSalt !== null && filters.maxSalt !== undefined) parts.push(`max_salt=${filters.maxSalt}`);
  if (filters.minSalt !== null && filters.minSalt !== undefined) parts.push(`min_salt=${filters.minSalt}`);
  if (filters.themes.length > 0) parts.push(`themes=${filters.themes.join(",")} (${filters.themesMode})`);
  return parts.length > 0 ? parts.join(" ") : "no filters";
}
