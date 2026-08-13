/**
 * 32-deck challenge tracker: one entry per color-identity combo, with a
 * status and a shortlist of candidate commanders, at most one chosen.
 * Ported from `commander_picker/challenge.py`. Entries aren't
 * pre-seeded: `getChallengeTracker` synthesizes all 32 at read time by
 * overlaying stored rows onto `colors.allSlugs()`.
 */

import type Database from "better-sqlite3";
import { ChallengeCommanderOption, ChallengeEntry, ChallengeStatus, colors, VALID_CHALLENGE_STATUSES } from "@commander-hq/shared";
import { SessionError } from "../db/sessions.js";

function requireKnownSlug(slug: string): void {
  if (!colors.COLOR_IDENTITY_BY_SLUG.has(slug)) {
    throw new SessionError(`Unknown color-identity slug ${JSON.stringify(slug)}`);
  }
}

interface StatusRow {
  slug: string;
  status: ChallengeStatus;
  notes: string | null;
  updated_at: number | null;
}

export function getChallengeTracker(db: Database.Database): ChallengeEntry[] {
  const statusRows = new Map(
    (db.prepare("SELECT * FROM challenge_tracker").all() as StatusRow[]).map((r) => [r.slug, r])
  );
  const commanderRows = db
    .prepare("SELECT slug, commander_name, is_chosen FROM challenge_commanders ORDER BY added_at")
    .all() as { slug: string; commander_name: string; is_chosen: number }[];

  const commandersBySlug = new Map<string, ChallengeCommanderOption[]>();
  for (const row of commanderRows) {
    if (!commandersBySlug.has(row.slug)) commandersBySlug.set(row.slug, []);
    commandersBySlug.get(row.slug)!.push({ name: row.commander_name, isChosen: Boolean(row.is_chosen) });
  }

  return colors.allSlugs().map((slug) => {
    const statusRow = statusRows.get(slug);
    return {
      slug,
      colors: colors.COLOR_IDENTITY_BY_SLUG.get(slug) ?? "",
      status: statusRow?.status ?? "not_started",
      notes: statusRow?.notes ?? null,
      commanders: commandersBySlug.get(slug) ?? [],
      updatedAt: statusRow?.updated_at ?? null,
    };
  });
}

function getChallengeEntry(db: Database.Database, slug: string): ChallengeEntry {
  const entry = getChallengeTracker(db).find((e) => e.slug === slug);
  if (!entry) throw new SessionError(`Unknown color-identity slug ${JSON.stringify(slug)}`);
  return entry;
}

/** Full overwrite of one combo's status/notes. */
export function setChallengeStatus(db: Database.Database, slug: string, status: string, notes: string | null = null): ChallengeEntry {
  requireKnownSlug(slug);
  if (!VALID_CHALLENGE_STATUSES.includes(status as ChallengeStatus)) {
    throw new SessionError(`status must be one of ${VALID_CHALLENGE_STATUSES.join(",")}, got ${JSON.stringify(status)}`);
  }

  db.prepare(
    `INSERT INTO challenge_tracker (slug, status, notes, updated_at)
     VALUES (?, ?, ?, ?)
     ON CONFLICT(slug) DO UPDATE SET
         status = excluded.status,
         notes = excluded.notes,
         updated_at = excluded.updated_at`
  ).run(slug, status, notes, Date.now() / 1000);
  return getChallengeEntry(db, slug);
}

/** Append one candidate to a combo's shortlist. No cap enforced; re-adding is a no-op. */
export function addChallengeCommander(db: Database.Database, slug: string, commanderName: string): ChallengeEntry {
  requireKnownSlug(slug);
  db.prepare("INSERT OR IGNORE INTO challenge_commanders (slug, commander_name, is_chosen, added_at) VALUES (?, ?, 0, ?)").run(
    slug,
    commanderName,
    Date.now() / 1000
  );
  return getChallengeEntry(db, slug);
}

export function removeChallengeCommander(db: Database.Database, slug: string, commanderName: string): ChallengeEntry {
  requireKnownSlug(slug);
  db.prepare("DELETE FROM challenge_commanders WHERE slug = ? AND commander_name = ?").run(slug, commanderName);
  return getChallengeEntry(db, slug);
}

/** Marks one candidate as chosen, unmarking any previous chosen entry for that slug. */
export function chooseChallengeCommander(db: Database.Database, slug: string, commanderName: string): ChallengeEntry {
  requireKnownSlug(slug);
  const existing = db
    .prepare("SELECT 1 FROM challenge_commanders WHERE slug = ? AND commander_name = ?")
    .get(slug, commanderName);
  if (!existing) {
    throw new SessionError(`${JSON.stringify(commanderName)} isn't a candidate for ${JSON.stringify(slug)} yet -- add it first.`);
  }

  const run = db.transaction(() => {
    db.prepare("UPDATE challenge_commanders SET is_chosen = 0 WHERE slug = ?").run(slug);
    db.prepare("UPDATE challenge_commanders SET is_chosen = 1 WHERE slug = ? AND commander_name = ?").run(slug, commanderName);
  });
  run();
  return getChallengeEntry(db, slug);
}

export function challengeSlugForCommander(colorIdentity: string): string {
  return colors.slugForColors(colorIdentity);
}
