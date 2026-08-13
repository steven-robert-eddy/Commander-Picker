/**
 * Pod tracker: multiplayer Elo for real EDH games, players, and decks.
 * Ported from `commander_picker/pods.py`.
 */

import type Database from "better-sqlite3";
import { randomUUID } from "node:crypto";
import { Deck, elo, PlayerRanking, PodGame, PodParticipant } from "@commander-hq/shared";
import { SessionError } from "../db/sessions.js";

function newId(): string {
  return randomUUID().replace(/-/g, "").slice(0, 12);
}

interface DeckRow {
  id: string;
  name: string;
  commander_name: string | null;
  color_identity: string | null;
  owner_name: string | null;
  rating: number;
  games_played: number;
  archived: number;
  created_at: number;
  updated_at: number;
}

function rowToDeck(row: DeckRow): Deck {
  return {
    id: row.id,
    name: row.name,
    commanderName: row.commander_name,
    colorIdentity: row.color_identity,
    ownerName: row.owner_name,
    rating: row.rating,
    gamesPlayed: row.games_played,
    archived: Boolean(row.archived),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

/** Add a deck to the persistent registry, starting at DEFAULT_RATING. */
export function registerDeck(
  db: Database.Database,
  name: string,
  options: { commanderName?: string | null; colorIdentity?: string | null; ownerName?: string | null } = {}
): Deck {
  if (!name.trim()) throw new SessionError("Deck name can't be empty.");
  const { commanderName = null, colorIdentity = null, ownerName = null } = options;
  const deckId = newId();
  const now = Date.now() / 1000;
  db.prepare(
    `INSERT INTO decks (id, name, commander_name, color_identity, owner_name, rating, games_played, archived, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)`
  ).run(deckId, name.trim(), commanderName, colorIdentity, ownerName, elo.DEFAULT_RATING, now, now);
  return getDeck(db, deckId);
}

export function getDeck(db: Database.Database, deckId: string): Deck {
  const row = db.prepare("SELECT * FROM decks WHERE id = ?").get(deckId) as DeckRow | undefined;
  if (!row) throw new SessionError(`No deck ${JSON.stringify(deckId)}`);
  return rowToDeck(row);
}

/** Every registered deck, active and archived alike, highest rating first. */
export function listDecks(db: Database.Database): Deck[] {
  const rows = db.prepare("SELECT * FROM decks ORDER BY rating DESC").all() as DeckRow[];
  return rows.map(rowToDeck);
}

function setDeckArchived(db: Database.Database, deckId: string, archived: boolean): Deck {
  getDeck(db, deckId); // throws SessionError if unknown
  db.prepare("UPDATE decks SET archived = ?, updated_at = ? WHERE id = ?").run(archived ? 1 : 0, Date.now() / 1000, deckId);
  return getDeck(db, deckId);
}

export function archiveDeck(db: Database.Database, deckId: string): Deck {
  return setDeckArchived(db, deckId, true);
}

export function unarchiveDeck(db: Database.Database, deckId: string): Deck {
  return setDeckArchived(db, deckId, false);
}

export function listPlayers(db: Database.Database): PlayerRanking[] {
  const rows = db.prepare("SELECT * FROM players ORDER BY rating DESC").all() as {
    name: string;
    rating: number;
    games_played: number;
    updated_at: number;
  }[];
  return rows.map((r) => ({ name: r.name, rating: r.rating, gamesPlayed: r.games_played, updatedAt: r.updated_at }));
}

function getOrSeedPlayerRating(db: Database.Database, name: string): number {
  const row = db.prepare("SELECT rating FROM players WHERE name = ?").get(name) as { rating: number } | undefined;
  return row ? row.rating : elo.DEFAULT_RATING;
}

export interface PodParticipantInput {
  playerName: string;
  deckId: string;
  isWinner: boolean;
}

/**
 * Record a completed pod game and update both player and deck ratings.
 * Requires at least 2 participants and exactly one winner.
 */
export function logPodGame(db: Database.Database, participants: PodParticipantInput[], notes = ""): PodGame {
  if (participants.length < 2) throw new SessionError("Need at least 2 participants to log a pod game.");
  const winners = participants.filter((p) => p.isWinner);
  if (winners.length !== 1) {
    throw new SessionError(`Exactly one participant must be marked as the winner (got ${winners.length}).`);
  }
  const playerNames = participants.map((p) => p.playerName);
  if (new Set(playerNames).size !== playerNames.length) {
    throw new SessionError("Each player can only appear once per game.");
  }
  const deckIds = participants.map((p) => p.deckId);
  if (new Set(deckIds).size !== deckIds.length) {
    throw new SessionError("Each deck can only appear once per game.");
  }

  const decksById = new Map<string, Deck>();
  for (const deckId of deckIds) {
    try {
      decksById.set(deckId, getDeck(db, deckId));
    } catch {
      throw new SessionError(`Unknown deck ${JSON.stringify(deckId)} -- register it first.`);
    }
  }

  const winnerIndex = participants.findIndex((p) => p.isWinner);
  const playerRatingsBefore = participants.map((p) => getOrSeedPlayerRating(db, p.playerName));
  const deckRatingsBefore = participants.map((p) => decksById.get(p.deckId)!.rating);
  const playerRatingsAfter = elo.updateMultiplayerRatings(playerRatingsBefore, winnerIndex);
  const deckRatingsAfter = elo.updateMultiplayerRatings(deckRatingsBefore, winnerIndex);

  const gameId = newId();
  const now = Date.now() / 1000;

  const resultParticipants: PodParticipant[] = [];
  const run = db.transaction(() => {
    db.prepare("INSERT INTO pod_games (id, created_at, notes) VALUES (?, ?, ?)").run(gameId, now, notes);

    participants.forEach((p, i) => {
      db.prepare(
        `INSERT INTO players (name, rating, games_played, updated_at)
         VALUES (?, ?, 1, ?)
         ON CONFLICT(name) DO UPDATE SET
             rating = excluded.rating,
             games_played = games_played + 1,
             updated_at = excluded.updated_at`
      ).run(p.playerName, playerRatingsAfter[i], now);
      db.prepare("UPDATE decks SET rating = ?, games_played = games_played + 1, updated_at = ? WHERE id = ?").run(
        deckRatingsAfter[i],
        now,
        p.deckId
      );
      db.prepare(
        `INSERT INTO pod_game_participants
           (game_id, player_name, deck_id, is_winner, player_rating_before, player_rating_after, deck_rating_before, deck_rating_after)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
      ).run(
        gameId,
        p.playerName,
        p.deckId,
        p.isWinner ? 1 : 0,
        playerRatingsBefore[i],
        playerRatingsAfter[i],
        deckRatingsBefore[i],
        deckRatingsAfter[i]
      );
      resultParticipants.push({
        playerName: p.playerName,
        deckId: p.deckId,
        deckName: decksById.get(p.deckId)!.name,
        isWinner: p.isWinner,
        playerRatingBefore: playerRatingsBefore[i],
        playerRatingAfter: playerRatingsAfter[i],
        deckRatingBefore: deckRatingsBefore[i],
        deckRatingAfter: deckRatingsAfter[i],
      });
    });
  });
  run();

  return { id: gameId, createdAt: now, notes, participants: resultParticipants };
}

function podGameParticipants(db: Database.Database, gameId: string): PodParticipant[] {
  const rows = db
    .prepare(
      `SELECT pgp.*, d.name AS deck_name FROM pod_game_participants pgp
       JOIN decks d ON d.id = pgp.deck_id WHERE pgp.game_id = ?`
    )
    .all(gameId) as {
    player_name: string;
    deck_id: string;
    deck_name: string;
    is_winner: number;
    player_rating_before: number;
    player_rating_after: number;
    deck_rating_before: number;
    deck_rating_after: number;
  }[];
  return rows.map((r) => ({
    playerName: r.player_name,
    deckId: r.deck_id,
    deckName: r.deck_name,
    isWinner: Boolean(r.is_winner),
    playerRatingBefore: r.player_rating_before,
    playerRatingAfter: r.player_rating_after,
    deckRatingBefore: r.deck_rating_before,
    deckRatingAfter: r.deck_rating_after,
  }));
}

export function listPodGames(db: Database.Database, limit: number | null = null): PodGame[] {
  const rows =
    limit !== null
      ? (db.prepare("SELECT * FROM pod_games ORDER BY created_at DESC LIMIT ?").all(limit) as any[])
      : (db.prepare("SELECT * FROM pod_games ORDER BY created_at DESC").all() as any[]);
  return rows.map((r) => ({
    id: r.id,
    createdAt: r.created_at,
    notes: r.notes,
    participants: podGameParticipants(db, r.id),
  }));
}

/** Undo the single most-recently-logged pod game, reverting every participant's rating. */
export function deleteLastPodGame(db: Database.Database): void {
  const gameRow = db.prepare("SELECT * FROM pod_games ORDER BY created_at DESC LIMIT 1").get() as { id: string } | undefined;
  if (!gameRow) throw new SessionError("No pod games to delete.");
  const gameId = gameRow.id;
  const participants = podGameParticipants(db, gameId);

  const run = db.transaction(() => {
    for (const p of participants) {
      const playerRow = db.prepare("SELECT games_played FROM players WHERE name = ?").get(p.playerName) as
        | { games_played: number }
        | undefined;
      if (playerRow && playerRow.games_played <= 1) {
        db.prepare("DELETE FROM players WHERE name = ?").run(p.playerName);
      } else {
        db.prepare("UPDATE players SET rating = ?, games_played = games_played - 1 WHERE name = ?").run(
          p.playerRatingBefore,
          p.playerName
        );
      }
      db.prepare("UPDATE decks SET rating = ?, games_played = games_played - 1 WHERE id = ?").run(p.deckRatingBefore, p.deckId);
    }
    db.prepare("DELETE FROM pod_game_participants WHERE game_id = ?").run(gameId);
    db.prepare("DELETE FROM pod_games WHERE id = ?").run(gameId);
  });
  run();
}
