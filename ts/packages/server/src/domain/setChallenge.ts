/**
 * Set challenge tracker: like the 32-deck color-identity challenge, but
 * one entry per EDHREC set release. Ported from
 * `commander_picker/set_challenge.py`. Unlike colors.allSlugs() (a small,
 * fixed list), the known-sets list is fully data-driven, so every
 * function here takes `knownSets` in from the caller.
 */

import type Database from "better-sqlite3";
import { ChallengeCommanderOption, ChallengeStatus, KnownSet, SetChallengeEntry, VALID_CHALLENGE_STATUSES } from "@commander-hq/shared";
import { SessionError } from "../db/sessions.js";

function slugSet(knownSets: KnownSet[]): Set<string> {
  return new Set(knownSets.map((s) => s.slug));
}

function requireKnownSlug(slug: string, knownSets: KnownSet[]): void {
  if (!slugSet(knownSets).has(slug)) {
    throw new SessionError(`Unknown set slug ${JSON.stringify(slug)}`);
  }
}

interface StatusRow {
  slug: string;
  status: ChallengeStatus;
  notes: string | null;
  updated_at: number | null;
}

/** Entries aren't pre-seeded: synthesizes one entry per `knownSets` at read time. */
export function getTracker(db: Database.Database, knownSets: KnownSet[]): SetChallengeEntry[] {
  const statusRows = new Map(
    (db.prepare("SELECT * FROM set_challenge_tracker").all() as StatusRow[]).map((r) => [r.slug, r])
  );
  const commanderRows = db
    .prepare("SELECT slug, commander_name, is_chosen FROM set_challenge_commanders ORDER BY added_at")
    .all() as { slug: string; commander_name: string; is_chosen: number }[];

  const commandersBySlug = new Map<string, ChallengeCommanderOption[]>();
  for (const row of commanderRows) {
    if (!commandersBySlug.has(row.slug)) commandersBySlug.set(row.slug, []);
    commandersBySlug.get(row.slug)!.push({ name: row.commander_name, isChosen: Boolean(row.is_chosen) });
  }

  return knownSets.map((s) => {
    const statusRow = statusRows.get(s.slug);
    return {
      slug: s.slug,
      name: s.name,
      status: statusRow?.status ?? "not_started",
      notes: statusRow?.notes ?? null,
      commanders: commandersBySlug.get(s.slug) ?? [],
      updatedAt: statusRow?.updated_at ?? null,
    };
  });
}

function getEntry(db: Database.Database, slug: string, knownSets: KnownSet[]): SetChallengeEntry {
  const entry = getTracker(db, knownSets).find((e) => e.slug === slug);
  if (!entry) throw new SessionError(`Unknown set slug ${JSON.stringify(slug)}`);
  return entry;
}

export function setStatus(
  db: Database.Database,
  knownSets: KnownSet[],
  slug: string,
  status: string,
  notes: string | null = null
): SetChallengeEntry {
  requireKnownSlug(slug, knownSets);
  if (!VALID_CHALLENGE_STATUSES.includes(status as ChallengeStatus)) {
    throw new SessionError(`status must be one of ${VALID_CHALLENGE_STATUSES.join(",")}, got ${JSON.stringify(status)}`);
  }

  db.prepare(
    `INSERT INTO set_challenge_tracker (slug, status, notes, updated_at)
     VALUES (?, ?, ?, ?)
     ON CONFLICT(slug) DO UPDATE SET
         status = excluded.status,
         notes = excluded.notes,
         updated_at = excluded.updated_at`
  ).run(slug, status, notes, Date.now() / 1000);
  return getEntry(db, slug, knownSets);
}

export function addCommander(db: Database.Database, knownSets: KnownSet[], slug: string, commanderName: string): SetChallengeEntry {
  requireKnownSlug(slug, knownSets);
  db.prepare("INSERT OR IGNORE INTO set_challenge_commanders (slug, commander_name, is_chosen, added_at) VALUES (?, ?, 0, ?)").run(
    slug,
    commanderName,
    Date.now() / 1000
  );
  return getEntry(db, slug, knownSets);
}

export function removeCommander(db: Database.Database, knownSets: KnownSet[], slug: string, commanderName: string): SetChallengeEntry {
  requireKnownSlug(slug, knownSets);
  db.prepare("DELETE FROM set_challenge_commanders WHERE slug = ? AND commander_name = ?").run(slug, commanderName);
  return getEntry(db, slug, knownSets);
}

export function chooseCommander(db: Database.Database, knownSets: KnownSet[], slug: string, commanderName: string): SetChallengeEntry {
  requireKnownSlug(slug, knownSets);
  const existing = db
    .prepare("SELECT 1 FROM set_challenge_commanders WHERE slug = ? AND commander_name = ?")
    .get(slug, commanderName);
  if (!existing) {
    throw new SessionError(`${JSON.stringify(commanderName)} isn't a candidate for ${JSON.stringify(slug)} yet -- add it first.`);
  }

  const run = db.transaction(() => {
    db.prepare("UPDATE set_challenge_commanders SET is_chosen = 0 WHERE slug = ?").run(slug);
    db.prepare("UPDATE set_challenge_commanders SET is_chosen = 1 WHERE slug = ? AND commander_name = ?").run(slug, commanderName);
  });
  run();
  return getEntry(db, slug, knownSets);
}
