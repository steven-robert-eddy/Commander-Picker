/**
 * Domain types shared between the server and the web client. Ported from
 * the shapes of `commander_picker`'s dataclasses/Pydantic models, renamed
 * to camelCase (this is a fresh API surface, not required to match the
 * Python app's wire format byte-for-byte).
 */

export type ColorMode = "subset" | "exact";
export type ThemesMode = "any" | "all";
export type SessionMode = "duel" | "bracket";
export type SessionStatus = "active" | "complete";
export type ChallengeStatus = "not_started" | "planning" | "building" | "complete";
export type FavoriteStatus = "owned" | "wishlist";

export const VALID_CHALLENGE_STATUSES: readonly ChallengeStatus[] = [
  "not_started",
  "planning",
  "building",
  "complete",
];
export const VALID_FAVORITE_STATUSES: readonly FavoriteStatus[] = ["owned", "wishlist"];

export const DEFAULT_MAX_DECKS = 10_000;
export const DEFAULT_MIN_DECKS = 100;
export const DEFAULT_MIN_POOL_SIZE = 4;
export const DEFAULT_MAX_POOL_SIZE = 40;
export const TOP_THEMES_PER_COMMANDER = 3;

/** Filtering criteria for narrowing the catalog down to a candidate pool. */
export interface PoolFilters {
  colors: string | null;
  colorMode: ColorMode;
  maxDecks: number | null;
  minDecks: number | null;
  themes: string[];
  themesMode: ThemesMode;
  maxPrice: number | null;
  maxSalt: number | null;
  minSalt: number | null;
  sets: string[];
}

/** The `POST /api/pool` and `POST /api/sessions` request body: filters plus pool sizing/mode. */
export interface FiltersBody extends PoolFilters {
  poolSize: number;
  minPoolSize: number;
  mode: SessionMode;
}

/** A commander as stored in the catalog DB. */
export interface Commander {
  name: string;
  colorIdentity: string;
  numDecks: number;
  edhrecUrl: string | null;
  themes: string[];
  salt: number | null;
  imageUrls: string[];
  price: number | null;
  rank: number | null;
  manaCost: string | null;
  typeLine: string | null;
  powerLevel: number | null;
}

export interface SessionInfo {
  id: string;
  description: string;
  status: SessionStatus;
  targetRounds: number;
  roundsCompleted: number;
  poolSize: number;
  mode: SessionMode;
}

/** A session candidate's full display detail, used to render a duel/bracket card. */
export interface CandidateDetail {
  name: string;
  colorIdentity: string;
  numDecks: number;
  edhrecUrl: string | null;
  themes: string[];
  imageUrls: string[];
  rating: number;
  rank: number | null;
  manaCost: string | null;
  typeLine: string | null;
  powerLevel: number | null;
}

export interface PairingPayload {
  round: number;
  targetRounds: number;
  candidates: [CandidateDetail, CandidateDetail];
  roundLabel?: string;
}

export interface BracketMatch {
  roundNum: number;
  slot: number;
  seedA: string | null;
  seedB: string | null;
  winner: string | null;
}

export interface BracketState {
  rounds: BracketMatch[][];
  champion: string | null;
}

export interface RankedCommander {
  name: string;
  rating: number;
  colorIdentity: string;
  numDecks: number;
  edhrecUrl: string | null;
  themes: string[];
  imageUrls: string[];
  powerLevel: number | null;
  favoriteStatus?: FavoriteStatus | null;
}

export interface GlobalRanking {
  name: string;
  rating: number;
  gamesPlayed: number;
  updatedAt: number;
  colorIdentity: string;
  numDecks: number;
  edhrecUrl: string | null;
  imageUrls: string[];
  favoriteStatus?: FavoriteStatus | null;
}

export interface ChallengeCommanderOption {
  name: string;
  isChosen: boolean;
  imageUrls?: string[];
  colorIdentity?: string | null;
}

export interface ChallengeEntry {
  slug: string;
  colors: string;
  status: ChallengeStatus;
  notes: string | null;
  commanders: ChallengeCommanderOption[];
  updatedAt: number | null;
}

export interface SetChallengeEntry {
  slug: string;
  name: string;
  status: ChallengeStatus;
  notes: string | null;
  commanders: ChallengeCommanderOption[];
  updatedAt: number | null;
}

export interface FavoriteEntry {
  commanderName: string;
  status: FavoriteStatus;
  updatedAt: number;
}

export interface Deck {
  id: string;
  name: string;
  commanderName: string | null;
  colorIdentity: string | null;
  ownerName: string | null;
  rating: number;
  gamesPlayed: number;
  archived: boolean;
  createdAt: number;
  updatedAt: number;
  imageUrls?: string[];
}

export interface PlayerRanking {
  name: string;
  rating: number;
  gamesPlayed: number;
  updatedAt: number;
}

export interface PodParticipant {
  playerName: string;
  deckId: string;
  deckName: string;
  isWinner: boolean;
  playerRatingBefore: number;
  playerRatingAfter: number;
  deckRatingBefore: number;
  deckRatingAfter: number;
}

export interface PodGame {
  id: string;
  createdAt: number;
  notes: string;
  participants: PodParticipant[];
}

export interface KnownSet {
  slug: string;
  name: string;
}

export interface SearchResult {
  name: string;
  colorIdentity: string;
  numDecks: number;
}
