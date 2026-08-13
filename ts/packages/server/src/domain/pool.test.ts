import Database from "better-sqlite3";
import { beforeEach, describe, expect, it } from "vitest";
import { buildPool, colorIdentityMatches, countMatches, PoolTooSmallError } from "./pool.js";
import type { PoolFilters } from "@commander-hq/shared";

function baseFilters(overrides: Partial<PoolFilters> = {}): PoolFilters {
  return {
    colors: null,
    colorMode: "subset",
    maxDecks: 10_000,
    minDecks: 0,
    themes: [],
    themesMode: "any",
    maxPrice: null,
    maxSalt: null,
    minSalt: null,
    sets: [],
    ...overrides,
  };
}

function makeTestCatalog(): Database.Database {
  const db = new Database(":memory:");
  db.exec(`
    CREATE TABLE commanders (
      name TEXT PRIMARY KEY, sanitized TEXT, color_identity TEXT NOT NULL, num_decks INTEGER NOT NULL,
      salt REAL, edhrec_url TEXT, image_urls TEXT NOT NULL DEFAULT '[]', price REAL, rank INTEGER,
      mana_cost TEXT, type_line TEXT, power_level INTEGER
    );
    CREATE TABLE commander_themes (commander_name TEXT NOT NULL, theme TEXT NOT NULL, num_decks INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (commander_name, theme));
    CREATE TABLE commander_sets (commander_name TEXT NOT NULL, set_slug TEXT NOT NULL, set_name TEXT NOT NULL, num_decks INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (commander_name, set_slug));
  `);
  const insertCommander = db.prepare(
    "INSERT INTO commanders (name, color_identity, num_decks, image_urls) VALUES (?, ?, ?, '[]')"
  );
  const insertTheme = db.prepare("INSERT INTO commander_themes (commander_name, theme, num_decks) VALUES (?, ?, ?)");

  insertCommander.run("Rakdos Commander", "BR", 500);
  insertTheme.run("Rakdos Commander", "aristocrats", 500);

  insertCommander.run("Mono Green Commander", "G", 300);
  insertTheme.run("Mono Green Commander", "ramp", 300);

  insertCommander.run("Colorless Commander", "", 200);

  insertCommander.run("Five Color Commander", "WUBRG", 100);

  return db;
}

describe("colorIdentityMatches", () => {
  it("treats colorless as pseudo-color C", () => {
    expect(colorIdentityMatches("", new Set(["C"]), "subset")).toBe(true);
    expect(colorIdentityMatches("", new Set(["W"]), "subset")).toBe(false);
    expect(colorIdentityMatches("", new Set(["C"]), "exact")).toBe(true);
  });

  it("subset mode allows a commander's colors to be a subset of allowed", () => {
    expect(colorIdentityMatches("BR", new Set(["B", "R", "G"]), "subset")).toBe(true);
    expect(colorIdentityMatches("BRG", new Set(["B", "R"]), "subset")).toBe(false);
  });

  it("exact mode requires an exact match", () => {
    expect(colorIdentityMatches("BR", new Set(["B", "R"]), "exact")).toBe(true);
    expect(colorIdentityMatches("BR", new Set(["B", "R", "G"]), "exact")).toBe(false);
  });
});

describe("buildPool / countMatches", () => {
  let db: Database.Database;
  beforeEach(() => {
    db = makeTestCatalog();
  });

  it("counts and returns all commanders with no filters", () => {
    const filters = baseFilters();
    expect(countMatches(db, filters)).toBe(4);
    expect(buildPool(db, filters, 40, 1)).toHaveLength(4);
  });

  it("filters by color subset", () => {
    const filters = baseFilters({ colors: "BRG" });
    const pool = buildPool(db, filters, 40, 1);
    expect(pool.map((c) => c.name).sort()).toEqual(["Mono Green Commander", "Rakdos Commander"]);
  });

  it("filters colorless via pseudo-color C", () => {
    const filters = baseFilters({ colors: "C" });
    const pool = buildPool(db, filters, 40, 1);
    expect(pool.map((c) => c.name)).toEqual(["Colorless Commander"]);
  });

  it("filters by theme", () => {
    const filters = baseFilters({ themes: ["ramp"] });
    const pool = buildPool(db, filters, 40, 1);
    expect(pool.map((c) => c.name)).toEqual(["Mono Green Commander"]);
  });

  it("throws PoolTooSmallError below minPoolSize", () => {
    const filters = baseFilters({ colors: "C" });
    expect(() => buildPool(db, filters, 40, 5)).toThrow(PoolTooSmallError);
  });

  it("samples down to maxPoolSize without exceeding it", () => {
    const filters = baseFilters();
    const pool = buildPool(db, filters, 2, 1);
    expect(pool).toHaveLength(2);
  });

  it("never excludes a commander with missing price/salt data even when the filter is set", () => {
    const filters = baseFilters({ maxPrice: 5, minSalt: 1 });
    expect(countMatches(db, filters)).toBe(4);
  });
});
