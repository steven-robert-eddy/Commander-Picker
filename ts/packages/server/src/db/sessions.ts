/**
 * Shared sessions.db infrastructure: connection + schema for picker
 * sessions/brackets, both challenge trackers, the pod tracker, and
 * favorites. Ported from `commander_picker/store.py`'s final schema --
 * a fresh implementation, so no legacy-column ALTER migrations are
 * needed (unlike the Python app, which has to support sessions.db files
 * created before some of these columns existed).
 *
 * Lives in a separate `data/sessions.db`, not `commanders.db` -- the
 * catalog DB is fully dropped and rebuilt on every `update-data` run,
 * which would silently wipe any in-progress or completed picker
 * sessions if they shared a file.
 */

import fs from "node:fs";
import Database from "better-sqlite3";
import { DATA_DIR, SESSIONS_DB_PATH } from "../paths.js";

export class SessionError extends Error {}

const SCHEMA = `
  CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY,
      created_at REAL NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL,
      target_rounds INTEGER NOT NULL,
      rounds_completed INTEGER NOT NULL DEFAULT 0,
      mode TEXT NOT NULL DEFAULT 'duel'
  );
  CREATE TABLE IF NOT EXISTS bracket_matches (
      session_id TEXT NOT NULL REFERENCES sessions(id),
      round_num INTEGER NOT NULL,
      slot INTEGER NOT NULL,
      seed_a TEXT,
      seed_b TEXT,
      winner TEXT,
      PRIMARY KEY (session_id, round_num, slot)
  );
  CREATE TABLE IF NOT EXISTS candidates (
      session_id TEXT NOT NULL REFERENCES sessions(id),
      commander_name TEXT NOT NULL,
      color_identity TEXT,
      num_decks INTEGER,
      edhrec_url TEXT,
      themes TEXT NOT NULL DEFAULT '',
      image_urls TEXT NOT NULL DEFAULT '[]',
      rating REAL NOT NULL,
      rank INTEGER,
      mana_cost TEXT,
      type_line TEXT,
      power_level INTEGER,
      PRIMARY KEY (session_id, commander_name)
  );
  CREATE TABLE IF NOT EXISTS comparisons (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL REFERENCES sessions(id),
      round_num INTEGER NOT NULL,
      winner TEXT NOT NULL,
      loser TEXT NOT NULL,
      created_at REAL NOT NULL,
      winner_rating_before REAL,
      loser_rating_before REAL,
      winner_global_rating_before REAL,
      loser_global_rating_before REAL
  );
  CREATE TABLE IF NOT EXISTS commander_ratings (
      commander_name TEXT PRIMARY KEY,
      rating REAL NOT NULL,
      games_played INTEGER NOT NULL DEFAULT 0,
      updated_at REAL NOT NULL
  );
  CREATE TABLE IF NOT EXISTS challenge_tracker (
      slug TEXT PRIMARY KEY,
      status TEXT NOT NULL DEFAULT 'not_started',
      notes TEXT,
      updated_at REAL
  );
  CREATE TABLE IF NOT EXISTS challenge_commanders (
      slug TEXT NOT NULL,
      commander_name TEXT NOT NULL,
      is_chosen INTEGER NOT NULL DEFAULT 0,
      added_at REAL,
      PRIMARY KEY (slug, commander_name)
  );
  CREATE TABLE IF NOT EXISTS set_challenge_tracker (
      slug TEXT PRIMARY KEY,
      status TEXT NOT NULL DEFAULT 'not_started',
      notes TEXT,
      updated_at REAL
  );
  CREATE TABLE IF NOT EXISTS set_challenge_commanders (
      slug TEXT NOT NULL,
      commander_name TEXT NOT NULL,
      is_chosen INTEGER NOT NULL DEFAULT 0,
      added_at REAL,
      PRIMARY KEY (slug, commander_name)
  );
  CREATE TABLE IF NOT EXISTS commander_favorites (
      commander_name TEXT PRIMARY KEY,
      status TEXT NOT NULL,
      updated_at REAL NOT NULL
  );
  CREATE TABLE IF NOT EXISTS players (
      name TEXT PRIMARY KEY,
      rating REAL NOT NULL,
      games_played INTEGER NOT NULL DEFAULT 0,
      updated_at REAL NOT NULL
  );
  CREATE TABLE IF NOT EXISTS decks (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      commander_name TEXT,
      color_identity TEXT,
      owner_name TEXT,
      rating REAL NOT NULL,
      games_played INTEGER NOT NULL DEFAULT 0,
      archived INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL
  );
  CREATE TABLE IF NOT EXISTS pod_games (
      id TEXT PRIMARY KEY,
      created_at REAL NOT NULL,
      notes TEXT NOT NULL DEFAULT ''
  );
  CREATE TABLE IF NOT EXISTS pod_game_participants (
      game_id TEXT NOT NULL REFERENCES pod_games(id),
      player_name TEXT NOT NULL,
      deck_id TEXT NOT NULL REFERENCES decks(id),
      is_winner INTEGER NOT NULL DEFAULT 0,
      player_rating_before REAL NOT NULL,
      player_rating_after REAL NOT NULL,
      deck_rating_before REAL NOT NULL,
      deck_rating_after REAL NOT NULL,
      PRIMARY KEY (game_id, player_name)
  );
`;

function ensureSchema(db: Database.Database): void {
  db.exec(SCHEMA);
}

/** Open (creating if needed) the sessions.db connection, with schema ensured. */
export function connect(dbPath: string = SESSIONS_DB_PATH): Database.Database {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  const db = new Database(dbPath);
  db.pragma("journal_mode = WAL");
  ensureSchema(db);
  return db;
}
