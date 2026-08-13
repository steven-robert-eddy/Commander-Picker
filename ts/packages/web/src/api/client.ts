import type {
  BracketState,
  ChallengeEntry,
  ColorMode,
  Commander,
  Deck,
  FavoriteEntry,
  FavoriteStatus,
  FiltersBody,
  GlobalRanking,
  KnownSet,
  PairingPayload,
  PlayerRanking,
  PodGame,
  RankedCommander,
  SearchResult,
  SessionInfo,
  SessionMode,
  SetChallengeEntry,
} from "@commander-hq/shared";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new ApiError(resp.status, (data as { error?: string }).error || `${method} ${path} failed (${resp.status})`);
  }
  return data as T;
}

export interface RegisterDeckBody {
  name: string;
  commanderName?: string | null;
  colorIdentity?: string | null;
  ownerName?: string | null;
}

export interface PodParticipantBody {
  playerName: string;
  deckId: string;
  isWinner: boolean;
}

export const api = {
  getThemes: () => request<{ slugs: string[] }>("GET", "/api/themes"),
  getSets: () => request<{ sets: KnownSet[] }>("GET", "/api/sets"),
  searchCommanders: (q: string, limit = 20) =>
    request<{ results: SearchResult[] }>("GET", `/api/commanders/search?q=${encodeURIComponent(q)}&limit=${limit}`),

  pool: (body: FiltersBody) => request<{ totalMatches: number; candidates: Commander[] }>("POST", "/api/pool", body),
  createSession: (body: FiltersBody) =>
    request<{ sessionId: string; info: SessionInfo; pairing: PairingPayload | null }>("POST", "/api/sessions", body),
  createCustomSession: (names: string[], mode: SessionMode) =>
    request<{ sessionId: string; info: SessionInfo; pairing: PairingPayload | null }>("POST", "/api/sessions/custom", {
      names,
      mode,
    }),
  listSessions: () => request<{ sessions: SessionInfo[] }>("GET", "/api/sessions"),
  getSession: (id: string) => request<SessionInfo>("GET", `/api/sessions/${id}`),
  getPairing: (id: string) => request<PairingPayload | null>("GET", `/api/sessions/${id}/pairing`),
  pick: (id: string, winner: string, loser: string) =>
    request<PairingPayload | null>("POST", `/api/sessions/${id}/pick`, { winner, loser }),
  undo: (id: string) => request<PairingPayload | null>("POST", `/api/sessions/${id}/undo`),
  finish: (id: string) =>
    request<{ rankings: RankedCommander[]; winnerChallengeSlug: string | null }>("POST", `/api/sessions/${id}/finish`),
  results: (id: string) =>
    request<{ rankings: RankedCommander[]; winnerChallengeSlug: string | null }>("GET", `/api/sessions/${id}/results`),
  bracket: (id: string) =>
    request<BracketState & { winnerChallengeSlug: string | null }>("GET", `/api/sessions/${id}/bracket`),

  leaderboard: (colors: string | null, colorMode: ColorMode, limit = 100) => {
    const params = new URLSearchParams();
    if (colors) params.set("colors", colors);
    params.set("colorMode", colorMode);
    params.set("limit", String(limit));
    return request<{ leaderboard: GlobalRanking[] }>("GET", `/api/leaderboard?${params.toString()}`);
  },
  resetLeaderboard: () => request<{ ok: true }>("DELETE", "/api/leaderboard"),

  getChallenge: () => request<{ entries: ChallengeEntry[] }>("GET", "/api/challenge"),
  setChallengeStatus: (slug: string, status: string, notes: string | null) =>
    request<ChallengeEntry>("PUT", `/api/challenge/${encodeURIComponent(slug)}`, { status, notes }),
  addChallengeCommander: (slug: string, commanderName: string) =>
    request<ChallengeEntry>("POST", `/api/challenge/${encodeURIComponent(slug)}/commanders`, { commanderName }),
  removeChallengeCommander: (slug: string, commanderName: string) =>
    request<ChallengeEntry>("DELETE", `/api/challenge/${encodeURIComponent(slug)}/commanders?commanderName=${encodeURIComponent(commanderName)}`),
  chooseChallengeCommander: (slug: string, commanderName: string) =>
    request<ChallengeEntry>("POST", `/api/challenge/${encodeURIComponent(slug)}/commanders/choose`, { commanderName }),
  addChallengeCommanderAuto: (commanderName: string, colorIdentity: string) =>
    request<ChallengeEntry>("POST", "/api/challenge/commanders", { commanderName, colorIdentity }),

  getSetChallenge: () => request<{ entries: SetChallengeEntry[] }>("GET", "/api/set-challenge"),
  setSetChallengeStatus: (slug: string, status: string, notes: string | null) =>
    request<SetChallengeEntry>("PUT", `/api/set-challenge/${encodeURIComponent(slug)}`, { status, notes }),
  addSetChallengeCommander: (slug: string, commanderName: string) =>
    request<SetChallengeEntry>("POST", `/api/set-challenge/${encodeURIComponent(slug)}/commanders`, { commanderName }),
  removeSetChallengeCommander: (slug: string, commanderName: string) =>
    request<SetChallengeEntry>(
      "DELETE",
      `/api/set-challenge/${encodeURIComponent(slug)}/commanders?commanderName=${encodeURIComponent(commanderName)}`
    ),
  chooseSetChallengeCommander: (slug: string, commanderName: string) =>
    request<SetChallengeEntry>("POST", `/api/set-challenge/${encodeURIComponent(slug)}/commanders/choose`, { commanderName }),
  searchSetChallengeCommanders: (slug: string, q: string, limit = 20) =>
    request<{ results: SearchResult[] }>(
      "GET",
      `/api/set-challenge/${encodeURIComponent(slug)}/commanders/search?q=${encodeURIComponent(q)}&limit=${limit}`
    ),

  setFavorite: (commanderName: string, status: FavoriteStatus) =>
    request<FavoriteEntry>("PUT", "/api/favorites", { commanderName, status }),
  clearFavorite: (commanderName: string) =>
    request<{ ok: true }>("DELETE", `/api/favorites?commanderName=${encodeURIComponent(commanderName)}`),

  listPlayers: () => request<{ players: PlayerRanking[] }>("GET", "/api/pod/players"),
  listDecks: () => request<{ decks: Deck[] }>("GET", "/api/pod/decks"),
  registerDeck: (body: RegisterDeckBody) => request<Deck>("POST", "/api/pod/decks", body),
  archiveDeck: (id: string) => request<Deck>("POST", `/api/pod/decks/${encodeURIComponent(id)}/archive`),
  unarchiveDeck: (id: string) => request<Deck>("POST", `/api/pod/decks/${encodeURIComponent(id)}/unarchive`),
  listPodGames: (limit?: number) => request<{ games: PodGame[] }>("GET", `/api/pod/games${limit ? `?limit=${limit}` : ""}`),
  logPodGame: (participants: PodParticipantBody[], notes: string) =>
    request<PodGame>("POST", "/api/pod/games", { participants, notes }),
  deleteLastPodGame: () => request<{ ok: true }>("DELETE", "/api/pod/games/last"),
};
