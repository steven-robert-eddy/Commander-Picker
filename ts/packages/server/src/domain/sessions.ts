/**
 * Picker/duel/bracket session persistence: candidate pools, ratings,
 * comparison history. Ported from `commander_picker/sessions.py`.
 */

import type Database from "better-sqlite3";
import { randomUUID } from "node:crypto";
import {
  BracketMatch,
  BracketState,
  CandidateDetail,
  Commander,
  elo,
  GlobalRanking,
  RankedCommander,
  SessionInfo,
  SessionMode,
} from "@commander-hq/shared";
import { SessionError } from "../db/sessions.js";
import { colorIdentityMatches } from "./pool.js";

function newId(): string {
  return randomUUID().replace(/-/g, "").slice(0, 12);
}

function globalRatings(db: Database.Database, names: string[]): Map<string, number> {
  const result = new Map<string, number>();
  if (names.length === 0) return result;
  const placeholders = names.map(() => "?").join(",");
  const rows = db
    .prepare(`SELECT commander_name, rating FROM commander_ratings WHERE commander_name IN (${placeholders})`)
    .all(...names) as { commander_name: string; rating: number }[];
  for (const r of rows) result.set(r.commander_name, r.rating);
  return result;
}

function bumpGlobalRating(db: Database.Database, name: string, newRating: number): void {
  db.prepare(
    `INSERT INTO commander_ratings (commander_name, rating, games_played, updated_at)
     VALUES (?, ?, 1, ?)
     ON CONFLICT(commander_name) DO UPDATE SET
         rating = excluded.rating,
         games_played = games_played + 1,
         updated_at = excluded.updated_at`
  ).run(name, newRating, Date.now() / 1000);
}

export function createSession(
  db: Database.Database,
  candidates: Commander[],
  description = "",
  mode: SessionMode = "duel"
): string {
  if (candidates.length < 2) {
    throw new SessionError("Need at least 2 candidates to start a picker session.");
  }
  if (mode === "bracket" && !elo.isValidBracketSize(candidates.length)) {
    throw new SessionError(
      `Bracket mode needs a candidate count that's a power of two (4, 8, 16, ...) -- got ${candidates.length}.`
    );
  }

  const sessionId = newId();
  const ratings = globalRatings(
    db,
    candidates.map((c) => c.name)
  );
  const targetRounds = mode === "bracket" ? elo.bracketRoundCount(candidates.length) : elo.targetRoundCount(candidates.length);

  const now = Date.now() / 1000;
  const insertSession = db.prepare(
    "INSERT INTO sessions (id, created_at, description, status, target_rounds, rounds_completed, mode) VALUES (?, ?, ?, 'active', ?, 0, ?)"
  );
  const insertCandidate = db.prepare(
    `INSERT INTO candidates
       (session_id, commander_name, color_identity, num_decks, edhrec_url, themes, image_urls, rating, rank, mana_cost, type_line, power_level)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  );

  const run = db.transaction(() => {
    insertSession.run(sessionId, now, description, targetRounds, mode);
    for (const c of candidates) {
      insertCandidate.run(
        sessionId,
        c.name,
        c.colorIdentity,
        c.numDecks,
        c.edhrecUrl,
        c.themes.join(","),
        JSON.stringify(c.imageUrls ?? []),
        ratings.get(c.name) ?? elo.DEFAULT_RATING,
        c.rank,
        c.manaCost,
        c.typeLine,
        c.powerLevel
      );
    }
    if (mode === "bracket") {
      createBracket(db, sessionId, candidates, ratings, targetRounds);
    }
  });
  run();

  return sessionId;
}

/**
 * Populate `bracket_matches` for every round upfront. Round 1 is fully
 * seeded (best-to-worst by current all-time rating, placed via
 * eloBracketSeedOrder so top seeds can't meet early). Later rounds' slots
 * are inserted with seedA/seedB left NULL, so the full bracket shape is
 * known immediately for rendering.
 */
function createBracket(
  db: Database.Database,
  sessionId: string,
  candidates: Commander[],
  ratings: Map<string, number>,
  roundCount: number
): void {
  const n = candidates.length;
  const seeded = [...candidates].sort((a, b) => (ratings.get(b.name) ?? elo.DEFAULT_RATING) - (ratings.get(a.name) ?? elo.DEFAULT_RATING));
  const order = elo.bracketSeedOrder(n); // 1-indexed seed positions, slot order
  const slotNames = order.map((seed) => seeded[seed - 1].name);

  const insertMatch = db.prepare(
    "INSERT INTO bracket_matches (session_id, round_num, slot, seed_a, seed_b, winner) VALUES (?, ?, ?, ?, ?, ?)"
  );

  const round1Slots = n / 2;
  for (let slot = 0; slot < round1Slots; slot++) {
    insertMatch.run(sessionId, 1, slot, slotNames[2 * slot], slotNames[2 * slot + 1], null);
  }
  for (let roundNum = 2; roundNum <= roundCount; roundNum++) {
    for (let slot = 0; slot < n / Math.pow(2, roundNum); slot++) {
      insertMatch.run(sessionId, roundNum, slot, null, null, null);
    }
  }
}

interface SessionRow {
  id: string;
  created_at: number;
  description: string;
  status: string;
  target_rounds: number;
  rounds_completed: number;
  mode: string;
}

export function getSession(db: Database.Database, sessionId: string): SessionInfo {
  const row = db.prepare("SELECT * FROM sessions WHERE id = ?").get(sessionId) as SessionRow | undefined;
  if (!row) throw new SessionError(`No session ${JSON.stringify(sessionId)}`);
  const poolSize = (db.prepare("SELECT COUNT(*) c FROM candidates WHERE session_id = ?").get(sessionId) as { c: number }).c;
  return {
    id: row.id,
    description: row.description,
    status: row.status as SessionInfo["status"],
    targetRounds: row.target_rounds,
    roundsCompleted: row.rounds_completed,
    poolSize,
    mode: row.mode as SessionMode,
  };
}

export function listSessions(db: Database.Database): SessionInfo[] {
  const rows = db.prepare("SELECT id FROM sessions ORDER BY created_at DESC").all() as { id: string }[];
  return rows.map((r) => getSession(db, r.id));
}

function sessionRatings(db: Database.Database, sessionId: string): Map<string, number> {
  const rows = db.prepare("SELECT commander_name, rating FROM candidates WHERE session_id = ?").all(sessionId) as {
    commander_name: string;
    rating: number;
  }[];
  return new Map(rows.map((r) => [r.commander_name, r.rating]));
}

function alreadyPaired(db: Database.Database, sessionId: string): Set<string> {
  const rows = db.prepare("SELECT winner, loser FROM comparisons WHERE session_id = ?").all(sessionId) as {
    winner: string;
    loser: string;
  }[];
  return new Set(rows.map((r) => elo.pairKey(r.winner, r.loser)));
}

interface CandidateRow {
  commander_name: string;
  color_identity: string;
  num_decks: number;
  edhrec_url: string | null;
  themes: string;
  image_urls: string;
  rating: number;
  rank: number | null;
  mana_cost: string | null;
  type_line: string | null;
  power_level: number | null;
}

/** Full candidate details for a session, keyed by commander name. */
export function getCandidates(db: Database.Database, sessionId: string): Map<string, CandidateDetail> {
  const rows = db.prepare("SELECT * FROM candidates WHERE session_id = ?").all(sessionId) as CandidateRow[];
  const result = new Map<string, CandidateDetail>();
  for (const r of rows) {
    result.set(r.commander_name, {
      name: r.commander_name,
      colorIdentity: r.color_identity,
      numDecks: r.num_decks,
      edhrecUrl: r.edhrec_url,
      themes: (r.themes || "").split(",").filter(Boolean),
      imageUrls: r.image_urls ? JSON.parse(r.image_urls) : [],
      rating: r.rating,
      rank: r.rank,
      manaCost: r.mana_cost,
      typeLine: r.type_line,
      powerLevel: r.power_level,
    });
  }
  return result;
}

/** Finalize the session if it's reached targetRounds and hasn't been marked complete yet. */
function maybeAutoFinish(db: Database.Database, sessionId: string): SessionInfo {
  let info = getSession(db, sessionId);
  if (info.status === "active" && info.roundsCompleted >= info.targetRounds) {
    finishSession(db, sessionId);
    info = getSession(db, sessionId);
  }
  return info;
}

/** The next pair to present, or null if the session isn't active. */
export function nextPairing(db: Database.Database, sessionId: string): [string, string] | null {
  const info = maybeAutoFinish(db, sessionId);
  if (info.status !== "active") return null;
  const ratings = sessionRatings(db, sessionId);
  const already = alreadyPaired(db, sessionId);
  return elo.choosePairing([...ratings.keys()], ratings, info.roundsCompleted, info.targetRounds, already);
}

export function recordPick(db: Database.Database, sessionId: string, winner: string, loser: string): void {
  let info = maybeAutoFinish(db, sessionId);
  if (info.status !== "active") {
    throw new SessionError(`Session ${JSON.stringify(sessionId)} is ${info.status}, not active -- can't record a pick.`);
  }

  const ratings = sessionRatings(db, sessionId);
  if (!ratings.has(winner) || !ratings.has(loser)) {
    throw new SessionError("winner/loser must both be candidates in this session");
  }

  const winnerRatingBefore = ratings.get(winner)!;
  const loserRatingBefore = ratings.get(loser)!;
  const globalBefore = globalRatings(db, [winner, loser]);
  const winnerGlobalRatingBefore = globalBefore.get(winner) ?? null;
  const loserGlobalRatingBefore = globalBefore.get(loser) ?? null;

  const [newWinner, newLoser] = elo.updateRatings(winnerRatingBefore, loserRatingBefore);

  const run = db.transaction(() => {
    db.prepare("UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?").run(newWinner, sessionId, winner);
    db.prepare("UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?").run(newLoser, sessionId, loser);
    bumpGlobalRating(db, winner, newWinner);
    bumpGlobalRating(db, loser, newLoser);

    const current = getSession(db, sessionId);
    db.prepare(
      `INSERT INTO comparisons
         (session_id, round_num, winner, loser, created_at,
          winner_rating_before, loser_rating_before, winner_global_rating_before, loser_global_rating_before)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      sessionId,
      current.roundsCompleted + 1,
      winner,
      loser,
      Date.now() / 1000,
      winnerRatingBefore,
      loserRatingBefore,
      winnerGlobalRatingBefore,
      loserGlobalRatingBefore
    );
    db.prepare("UPDATE sessions SET rounds_completed = rounds_completed + 1 WHERE id = ?").run(sessionId);
  });
  run();

  maybeAutoFinish(db, sessionId);
}

interface ComparisonRow {
  id: number;
  winner: string;
  loser: string;
  winner_rating_before: number | null;
  loser_rating_before: number | null;
  winner_global_rating_before: number | null;
  loser_global_rating_before: number | null;
}

/** Revert the most recently recorded pick in a duel-mode session. Only ever reverses the single most recent pick. */
export function undoLastPick(db: Database.Database, sessionId: string): void {
  const info = getSession(db, sessionId);
  if (info.mode !== "duel") {
    throw new SessionError("Undo isn't available for bracket sessions yet.");
  }

  const row = db
    .prepare("SELECT * FROM comparisons WHERE session_id = ? ORDER BY id DESC LIMIT 1")
    .get(sessionId) as ComparisonRow | undefined;
  if (!row) throw new SessionError("No picks to undo.");
  if (row.winner_rating_before === null) {
    throw new SessionError("Can't undo this pick -- it predates undo support.");
  }

  const { winner, loser } = row;

  const run = db.transaction(() => {
    db.prepare("UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?").run(
      row.winner_rating_before,
      sessionId,
      winner
    );
    db.prepare("UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?").run(
      row.loser_rating_before,
      sessionId,
      loser
    );

    for (const [name, before] of [
      [winner, row.winner_global_rating_before],
      [loser, row.loser_global_rating_before],
    ] as [string, number | null][]) {
      if (before === null) {
        db.prepare("DELETE FROM commander_ratings WHERE commander_name = ?").run(name);
      } else {
        db.prepare("UPDATE commander_ratings SET rating = ?, games_played = games_played - 1 WHERE commander_name = ?").run(
          before,
          name
        );
      }
    }

    db.prepare("DELETE FROM comparisons WHERE id = ?").run(row.id);
    db.prepare("UPDATE sessions SET rounds_completed = rounds_completed - 1 WHERE id = ?").run(sessionId);
    if (info.status === "complete") {
      db.prepare("UPDATE sessions SET status = 'active' WHERE id = ?").run(sessionId);
    }
  });
  run();
}

export function finishSession(db: Database.Database, sessionId: string): void {
  db.prepare("UPDATE sessions SET status = 'complete' WHERE id = ?").run(sessionId);
}

/** The next ready bracket match: [roundNum, slot, seedA, seedB], or null. */
export function nextBracketMatch(db: Database.Database, sessionId: string): [number, number, string, string] | null {
  const info = getSession(db, sessionId);
  if (info.status !== "active") return null;
  const row = db
    .prepare(
      `SELECT round_num, slot, seed_a, seed_b FROM bracket_matches
       WHERE session_id = ? AND winner IS NULL AND seed_a IS NOT NULL AND seed_b IS NOT NULL
       ORDER BY round_num, slot LIMIT 1`
    )
    .get(sessionId) as { round_num: number; slot: number; seed_a: string; seed_b: string } | undefined;
  if (!row) return null;
  return [row.round_num, row.slot, row.seed_a, row.seed_b];
}

/** Record the outcome of a bracket match and advance the bracket. */
export function recordBracketPick(db: Database.Database, sessionId: string, winner: string, loser: string): void {
  const info = getSession(db, sessionId);
  if (info.status !== "active") {
    throw new SessionError(`Session ${JSON.stringify(sessionId)} is ${info.status}, not active -- can't record a pick.`);
  }

  const match = db
    .prepare(
      `SELECT round_num, slot FROM bracket_matches
       WHERE session_id = ? AND winner IS NULL AND seed_a IS NOT NULL AND seed_b IS NOT NULL
       AND ((seed_a = ? AND seed_b = ?) OR (seed_a = ? AND seed_b = ?))
       ORDER BY round_num, slot LIMIT 1`
    )
    .get(sessionId, winner, loser, loser, winner) as { round_num: number; slot: number } | undefined;
  if (!match) throw new SessionError("winner/loser don't match any ready bracket match in this session");
  const { round_num: roundNum, slot } = match;

  const ratings = sessionRatings(db, sessionId);
  const [newWinner, newLoser] = elo.updateRatings(ratings.get(winner)!, ratings.get(loser)!, elo.BRACKET_K_FACTOR);

  const run = db.transaction(() => {
    db.prepare("UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?").run(newWinner, sessionId, winner);
    db.prepare("UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?").run(newLoser, sessionId, loser);
    bumpGlobalRating(db, winner, newWinner);
    bumpGlobalRating(db, loser, newLoser);

    db.prepare("UPDATE bracket_matches SET winner = ? WHERE session_id = ? AND round_num = ? AND slot = ?").run(
      winner,
      sessionId,
      roundNum,
      slot
    );
    db.prepare("INSERT INTO comparisons (session_id, round_num, winner, loser, created_at) VALUES (?, ?, ?, ?, ?)").run(
      sessionId,
      roundNum,
      winner,
      loser,
      Date.now() / 1000
    );

    const nextRound = roundNum + 1;
    if (nextRound <= info.targetRounds) {
      const nextSlot = Math.floor(slot / 2);
      const column = slot % 2 === 0 ? "seed_a" : "seed_b";
      db.prepare(`UPDATE bracket_matches SET ${column} = ? WHERE session_id = ? AND round_num = ? AND slot = ?`).run(
        winner,
        sessionId,
        nextRound,
        nextSlot
      );
    }

    const remainingInRound = (
      db
        .prepare("SELECT COUNT(*) c FROM bracket_matches WHERE session_id = ? AND round_num = ? AND winner IS NULL")
        .get(sessionId, roundNum) as { c: number }
    ).c;
    if (remainingInRound === 0) {
      db.prepare("UPDATE sessions SET rounds_completed = rounds_completed + 1 WHERE id = ?").run(sessionId);
      if (roundNum === info.targetRounds) {
        db.prepare("UPDATE sessions SET status = 'complete' WHERE id = ?").run(sessionId);
      }
    }
  });
  run();
}

/** Full bracket tree for a session -- the single source of truth for both the in-progress and final views. */
export function getBracket(db: Database.Database, sessionId: string): BracketState {
  getSession(db, sessionId); // throws SessionError if the session doesn't exist
  const rows = db
    .prepare("SELECT round_num, slot, seed_a, seed_b, winner FROM bracket_matches WHERE session_id = ? ORDER BY round_num, slot")
    .all(sessionId) as { round_num: number; slot: number; seed_a: string | null; seed_b: string | null; winner: string | null }[];

  const byRound = new Map<number, BracketMatch[]>();
  for (const r of rows) {
    if (!byRound.has(r.round_num)) byRound.set(r.round_num, []);
    byRound.get(r.round_num)!.push({ roundNum: r.round_num, slot: r.slot, seedA: r.seed_a, seedB: r.seed_b, winner: r.winner });
  }
  const rounds = [...byRound.keys()].sort((a, b) => a - b).map((n) => byRound.get(n)!);
  let champion: string | null = null;
  if (rounds.length > 0 && rounds.at(-1)!.length === 1) {
    champion = rounds.at(-1)![0].winner;
  }
  return { rounds, champion };
}

export function getRankings(db: Database.Database, sessionId: string): RankedCommander[] {
  const rows = db
    .prepare(
      `SELECT commander_name, rating, color_identity, num_decks, edhrec_url, themes, image_urls, power_level
       FROM candidates WHERE session_id = ? ORDER BY rating DESC`
    )
    .all(sessionId) as CandidateRow[];
  return rows.map((r) => ({
    name: r.commander_name,
    rating: r.rating,
    colorIdentity: r.color_identity,
    numDecks: r.num_decks,
    edhrecUrl: r.edhrec_url,
    themes: (r.themes || "").split(",").filter(Boolean),
    imageUrls: r.image_urls ? JSON.parse(r.image_urls) : [],
    powerLevel: r.power_level,
  }));
}

/**
 * All-time ranking across every session ever played, highest rating
 * first. `colors`/`colorMode` reuse `colorIdentityMatches`, applied here
 * in JS after the query (color identity isn't a live SQL column here --
 * it comes from the joined denormalized snapshot).
 */
export function getLeaderboard(
  db: Database.Database,
  options: { limit?: number | null; colors?: string | null; colorMode?: "subset" | "exact" } = {}
): GlobalRanking[] {
  const { limit = null, colors = null, colorMode = "subset" } = options;
  const rows = db
    .prepare(
      `SELECT
           cr.commander_name,
           cr.rating,
           cr.games_played,
           cr.updated_at,
           latest.color_identity,
           latest.num_decks,
           latest.edhrec_url,
           latest.image_urls
       FROM commander_ratings cr
       LEFT JOIN (
           SELECT commander_name, color_identity, num_decks, edhrec_url, image_urls,
                  ROW_NUMBER() OVER (PARTITION BY commander_name ORDER BY rowid DESC) AS rn
           FROM candidates
       ) latest ON latest.commander_name = cr.commander_name AND latest.rn = 1
       ORDER BY cr.rating DESC`
    )
    .all() as {
    commander_name: string;
    rating: number;
    games_played: number;
    updated_at: number;
    color_identity: string | null;
    num_decks: number | null;
    edhrec_url: string | null;
    image_urls: string | null;
  }[];

  let ranked: GlobalRanking[] = rows.map((r) => ({
    name: r.commander_name,
    rating: r.rating,
    gamesPlayed: r.games_played,
    updatedAt: r.updated_at,
    colorIdentity: r.color_identity ?? "",
    numDecks: r.num_decks ?? 0,
    edhrecUrl: r.edhrec_url,
    imageUrls: r.image_urls ? JSON.parse(r.image_urls) : [],
  }));

  if (colors) {
    const allowed = new Set(colors.toUpperCase().split(""));
    ranked = ranked.filter((r) => colorIdentityMatches(r.colorIdentity, allowed, colorMode));
  }
  if (limit !== null) {
    ranked = ranked.slice(0, limit);
  }
  return ranked;
}

/** Permanently erase every commander's all-time rating/games_played. Session history is untouched. */
export function resetLeaderboard(db: Database.Database): void {
  db.prepare("DELETE FROM commander_ratings").run();
}

export interface RefreshResult {
  updated: number;
  notFound: number;
}

/** Resync candidates' denormalized display metadata from the current catalog. */
export function refreshCandidateMetadata(sessionsDb: Database.Database, catalogDb: Database.Database): RefreshResult {
  const names = (sessionsDb.prepare("SELECT DISTINCT commander_name FROM candidates").all() as { commander_name: string }[]).map(
    (r) => r.commander_name
  );
  let updated = 0;
  let notFound = 0;
  for (const name of names) {
    const row = catalogDb
      .prepare("SELECT color_identity, num_decks, edhrec_url, image_urls FROM commanders WHERE name = ?")
      .get(name) as { color_identity: string; num_decks: number; edhrec_url: string | null; image_urls: string } | undefined;
    if (!row) {
      notFound++;
      continue;
    }
    sessionsDb
      .prepare("UPDATE candidates SET color_identity = ?, num_decks = ?, edhrec_url = ?, image_urls = ? WHERE commander_name = ?")
      .run(row.color_identity, row.num_decks, row.edhrec_url, row.image_urls, name);
    updated++;
  }
  return { updated, notFound };
}
