/**
 * Load cached EDHREC pages into a queryable SQLite database
 * (`data/commanders.db`). Ported from `commander_picker/db.py`.
 */

import fs from "node:fs";
import Database from "better-sqlite3";
import { colors, themes } from "@commander-hq/shared";
import * as edhrec from "../clients/edhrec.js";
import * as scryfall from "../clients/scryfall.js";
import { CATALOG_DB_PATH, DATA_DIR } from "../paths.js";

export class DbError extends Error {}

// Keep only the highest-count tags per commander -- a popular commander
// can have 50-100+ EDHREC taglinks, many down to count:1 (noise).
const TOP_TAGS_PER_COMMANDER = 10;

interface CommanderRecord {
  name: string;
  sanitized: string;
  colorIdentity: string; // e.g. "BR", "" for colorless
  numDecks: number;
  edhrecUrl: string | null;
  themes: Set<string>;
  themeDecks: Map<string, number>;
  salt: number | null;
  imageUrls: string[];
  price: number | null;
  rank: number | null;
  manaCost: string | null;
  typeLine: string | null;
  powerLevel: number | null;
}

function cardviewsFromPage(pageJson: any): any[] {
  const cardlists = pageJson?.container?.json_dict?.cardlists ?? [];
  return cardlists.flatMap((cl: any) => cl.cardviews ?? []);
}

/**
 * Commander cardviews on a set page, excluding reprints. Two different
 * tagging shapes exist across EDHREC's set pages: sets with a dedicated
 * Commander-precon product split into e.g. `commanders(sos)`/`commanders(soc)`,
 * while older/simpler sets use a single plain `commanders` tag. Both can
 * also carry a `commanders(reprints)` cardlist, deliberately excluded.
 */
function setCommanderCardviews(pageJson: any): any[] {
  const cardlists = pageJson?.container?.json_dict?.cardlists ?? [];
  const views: any[] = [];
  for (const cardlist of cardlists) {
    const tag = cardlist.tag ?? "";
    const isCommandersList = tag === "commanders" || (tag.startsWith("commanders(") && tag !== "commanders(reprints)");
    if (!isCommandersList) continue;
    views.push(...(cardlist.cardviews ?? []));
  }
  return views;
}

function cardviewToRecord(cardview: any, colorIdentity: string): CommanderRecord {
  const url = cardview.url;
  return {
    name: cardview.name,
    sanitized: cardview.sanitized ?? "",
    colorIdentity,
    numDecks: cardview.num_decks ?? 0,
    edhrecUrl: url ? `https://edhrec.com${url}` : null,
    themes: new Set(),
    themeDecks: new Map(),
    salt: null,
    imageUrls: [],
    price: null,
    rank: cardview.rank ?? null,
    manaCost: null,
    typeLine: null,
    powerLevel: null,
  };
}

function availableSlugs(kind: edhrec.PageKind, requested: string[]): string[] {
  return requested.filter((slug) => edhrec.pageExists(kind, slug));
}

/**
 * Merge salt + top taglinks-derived themes from a cached per-commander
 * detail page into an already-built CommanderRecord.
 */
function applyCommanderDetail(record: CommanderRecord, payload: any): void {
  const card = payload.card ?? {};
  record.salt = card.salt ?? null;

  const taglinks: any[] = payload.panels?.taglinks ?? [];
  const topTags = [...taglinks].sort((a, b) => (b.count ?? 0) - (a.count ?? 0)).slice(0, TOP_TAGS_PER_COMMANDER);
  for (const t of topTags) {
    const slug = t.slug;
    if (!slug) continue;
    record.themes.add(slug);
    record.themeDecks.set(slug, t.count ?? 0);
  }

  const bracketCounts: Record<string, number> = payload.bracket_counts ?? {};
  const entries = Object.entries(bracketCounts);
  if (entries.length > 0) {
    const dominant = entries.reduce((best, cur) => (cur[1] > best[1] ? cur : best));
    record.powerLevel = parseInt(dominant[0], 10);
  }
}

/**
 * Build the merged commander map from whatever cached pages exist. Color
 * pages are authoritative for identity/deck-count fields; theme pages
 * only contribute theme tags for commanders already found on a color
 * page; a commander's own detail page (if cached) is applied last.
 */
export function loadCommanders(colorSlugs?: string[] | null, themeSlugs?: string[] | null): Map<string, CommanderRecord> {
  const resolvedColorSlugs = availableSlugs("color", colorSlugs ?? colors.allSlugs());
  const resolvedThemeSlugs = availableSlugs("theme", themeSlugs ?? [...themes.THEME_SLUGS]);

  if (resolvedColorSlugs.length === 0) {
    throw new DbError("No cached EDHREC color pages found. Run `update-data` first.");
  }

  const commanders = new Map<string, CommanderRecord>();
  for (const slug of resolvedColorSlugs) {
    const colorIdentity = colors.COLOR_IDENTITY_BY_SLUG.get(slug) ?? "";
    const page = edhrec.loadPage("color", slug);
    for (const cardview of cardviewsFromPage(page)) {
      const record = cardviewToRecord(cardview, colorIdentity);
      commanders.set(record.name, record);
    }
  }

  for (const slug of resolvedThemeSlugs) {
    const page = edhrec.loadPage("theme", slug);
    for (const cardview of cardviewsFromPage(page)) {
      const name = cardview.name;
      const record = commanders.get(name);
      if (record) {
        record.themes.add(slug);
        record.themeDecks.set(slug, cardview.num_decks ?? 0);
      }
    }
  }

  for (const record of commanders.values()) {
    if (edhrec.pageExists("commander", record.sanitized)) {
      const payload = edhrec.loadPage("commander", record.sanitized);
      applyCommanderDetail(record, payload);
    }
  }

  return commanders;
}

interface CommanderSetRow {
  commanderName: string;
  setSlug: string;
  setName: string;
  numDecks: number;
}

function commanderSetRows(setSlugs: string[], commanders: Map<string, CommanderRecord>): CommanderSetRow[] {
  const rows: CommanderSetRow[] = [];
  for (const slug of setSlugs) {
    const page = edhrec.loadPage("set", slug);
    const setName = page.header || slug;
    for (const cardview of setCommanderCardviews(page)) {
      const name = cardview.name;
      if (!commanders.has(name)) continue;
      rows.push({ commanderName: name, setSlug: slug, setName, numDecks: cardview.num_decks ?? 0 });
    }
  }
  return rows;
}

const SCHEMA = `
  CREATE TABLE commanders (
      name TEXT PRIMARY KEY,
      sanitized TEXT,
      color_identity TEXT NOT NULL,
      num_decks INTEGER NOT NULL,
      salt REAL,
      edhrec_url TEXT,
      image_urls TEXT NOT NULL DEFAULT '[]',
      price REAL,
      rank INTEGER,
      mana_cost TEXT,
      type_line TEXT,
      power_level INTEGER
  );
  CREATE TABLE commander_themes (
      commander_name TEXT NOT NULL REFERENCES commanders(name),
      theme TEXT NOT NULL,
      num_decks INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (commander_name, theme)
  );
  CREATE TABLE commander_sets (
      commander_name TEXT NOT NULL REFERENCES commanders(name),
      set_slug TEXT NOT NULL,
      set_name TEXT NOT NULL,
      num_decks INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (commander_name, set_slug)
  );
  CREATE INDEX idx_commanders_color_identity ON commanders(color_identity);
  CREATE INDEX idx_commanders_num_decks ON commanders(num_decks);
  CREATE INDEX idx_commander_themes_theme ON commander_themes(theme);
  CREATE INDEX idx_commander_sets_slug ON commander_sets(set_slug);
`;

export interface BuildDatabaseOptions {
  colorSlugs?: string[] | null;
  themeSlugs?: string[] | null;
  setSlugs?: string[] | null;
  dbPath?: string;
  imageLookup?: Map<string, string[]> | null;
  cardMetaLookup?: Map<string, scryfall.CardMeta> | null;
}

/** Load cached pages and (re)write `data/commanders.db` from scratch. */
export function buildDatabase(options: BuildDatabaseOptions = {}): string {
  const { colorSlugs, themeSlugs, setSlugs, dbPath = CATALOG_DB_PATH, imageLookup, cardMetaLookup } = options;

  const commanders = loadCommanders(colorSlugs, themeSlugs);
  const resolvedSetSlugs = availableSlugs("set", setSlugs ?? edhrec.cachedSlugs("set"));
  const commanderSets = commanderSetRows(resolvedSetSlugs, commanders);

  if (imageLookup) {
    for (const record of commanders.values()) {
      record.imageUrls = scryfall.resolveImageUrls(record.name, imageLookup);
    }
  }
  if (cardMetaLookup) {
    for (const record of commanders.values()) {
      const meta = scryfall.resolveCardMeta(record.name, cardMetaLookup);
      record.manaCost = meta.manaCost;
      record.typeLine = meta.typeLine;
      record.price = meta.priceUsd;
    }
  }

  fs.mkdirSync(DATA_DIR, { recursive: true });
  if (fs.existsSync(dbPath)) fs.unlinkSync(dbPath);

  const db = new Database(dbPath);
  try {
    db.exec(SCHEMA);

    const insertSet = db.prepare(
      "INSERT INTO commander_sets (commander_name, set_slug, set_name, num_decks) VALUES (?, ?, ?, ?)"
    );
    const insertCommander = db.prepare(
      `INSERT INTO commanders
         (name, sanitized, color_identity, num_decks, salt, edhrec_url, image_urls, price, rank, mana_cost, type_line, power_level)
       VALUES (@name, @sanitized, @colorIdentity, @numDecks, @salt, @edhrecUrl, @imageUrls, @price, @rank, @manaCost, @typeLine, @powerLevel)`
    );
    const insertTheme = db.prepare(
      "INSERT INTO commander_themes (commander_name, theme, num_decks) VALUES (?, ?, ?)"
    );

    const writeAll = db.transaction(() => {
      for (const row of commanderSets) {
        insertSet.run(row.commanderName, row.setSlug, row.setName, row.numDecks);
      }
      for (const record of commanders.values()) {
        insertCommander.run({
          name: record.name,
          sanitized: record.sanitized,
          colorIdentity: record.colorIdentity,
          numDecks: record.numDecks,
          salt: record.salt,
          edhrecUrl: record.edhrecUrl,
          imageUrls: JSON.stringify(record.imageUrls),
          price: record.price,
          rank: record.rank,
          manaCost: record.manaCost,
          typeLine: record.typeLine,
          powerLevel: record.powerLevel,
        });
        for (const theme of [...record.themes].sort()) {
          insertTheme.run(record.name, theme, record.themeDecks.get(theme) ?? 0);
        }
      }
    });
    writeAll();
  } finally {
    db.close();
  }

  return dbPath;
}

/** Open a read/write connection to `commanders.db`; throws DbError if it doesn't exist yet. */
export function connect(dbPath: string = CATALOG_DB_PATH): Database.Database {
  if (!fs.existsSync(dbPath)) {
    throw new DbError(`${dbPath} does not exist yet. Run \`update-data\` first.`);
  }
  return new Database(dbPath);
}
