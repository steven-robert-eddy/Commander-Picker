/**
 * Per-commander owned/wishlist tracking, independent of any session.
 * Ported from `commander_picker/favorites.py`. "Not favorited" has no
 * stored row.
 */

import type Database from "better-sqlite3";
import { FavoriteEntry, FavoriteStatus, VALID_FAVORITE_STATUSES } from "@commander-hq/shared";
import { SessionError } from "../db/sessions.js";

export function setFavoriteStatus(db: Database.Database, commanderName: string, status: string): FavoriteEntry {
  if (!VALID_FAVORITE_STATUSES.includes(status as FavoriteStatus)) {
    throw new SessionError(`status must be one of ${VALID_FAVORITE_STATUSES.join(",")}, got ${JSON.stringify(status)}`);
  }
  const updatedAt = Date.now() / 1000;
  db.prepare(
    `INSERT INTO commander_favorites (commander_name, status, updated_at)
     VALUES (?, ?, ?)
     ON CONFLICT(commander_name) DO UPDATE SET
         status = excluded.status,
         updated_at = excluded.updated_at`
  ).run(commanderName, status, updatedAt);
  return { commanderName, status: status as FavoriteStatus, updatedAt };
}

export function clearFavorite(db: Database.Database, commanderName: string): void {
  db.prepare("DELETE FROM commander_favorites WHERE commander_name = ?").run(commanderName);
}

/** Bulk name -> status lookup, for enriching a list of rendered rows. */
export function favoritesByName(db: Database.Database, names: string[]): Map<string, FavoriteStatus> {
  const result = new Map<string, FavoriteStatus>();
  if (names.length === 0) return result;
  const placeholders = names.map(() => "?").join(",");
  const rows = db
    .prepare(`SELECT commander_name, status FROM commander_favorites WHERE commander_name IN (${placeholders})`)
    .all(...names) as { commander_name: string; status: FavoriteStatus }[];
  for (const r of rows) result.set(r.commander_name, r.status);
  return result;
}
