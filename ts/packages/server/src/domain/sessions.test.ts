import type { Commander } from "@commander-hq/shared";
import { beforeEach, describe, expect, it } from "vitest";
import { connect } from "../db/sessions.js";
import {
  createSession,
  getBracket,
  getRankings,
  getSession,
  nextBracketMatch,
  nextPairing,
  recordBracketPick,
  recordPick,
  undoLastPick,
} from "./sessions.js";

function makeCommander(name: string, overrides: Partial<Commander> = {}): Commander {
  return {
    name,
    colorIdentity: "BR",
    numDecks: 100,
    edhrecUrl: null,
    themes: [],
    salt: null,
    imageUrls: [],
    price: null,
    rank: null,
    manaCost: null,
    typeLine: null,
    powerLevel: null,
    ...overrides,
  };
}

describe("duel sessions", () => {
  let db: ReturnType<typeof connect>;
  beforeEach(() => {
    db = connect(":memory:");
  });

  it("creates a session with the n*log2(n) target and seeds default ratings", () => {
    const candidates = ["a", "b", "c", "d"].map((n) => makeCommander(n));
    const id = createSession(db, candidates, "test", "duel");
    const info = getSession(db, id);
    expect(info.mode).toBe("duel");
    expect(info.poolSize).toBe(4);
    expect(info.targetRounds).toBe(Math.max(1, Math.round(4 * Math.log2(4))));
    expect(info.status).toBe("active");
  });

  it("records a pick and updates ratings + rounds", () => {
    const candidates = ["a", "b"].map((n) => makeCommander(n));
    const id = createSession(db, candidates, "test", "duel");
    const pairing = nextPairing(db, id)!;
    expect(pairing).not.toBeNull();
    recordPick(db, id, "a", "b");
    const info = getSession(db, id);
    expect(info.roundsCompleted).toBe(1);
    const rankings = getRankings(db, id);
    expect(rankings[0].name).toBe("a");
    expect(rankings[0].rating).toBeGreaterThan(1000);
  });

  it("undo restores exact pre-pick ratings and decrements rounds", () => {
    const candidates = ["a", "b"].map((n) => makeCommander(n));
    const id = createSession(db, candidates, "test", "duel");
    recordPick(db, id, "a", "b");
    undoLastPick(db, id);
    const info = getSession(db, id);
    expect(info.roundsCompleted).toBe(0);
    const rankings = getRankings(db, id);
    expect(rankings.every((r) => r.rating === 1000)).toBe(true);
  });

  it("auto-finishes once target rounds are reached", () => {
    const candidates = ["a", "b"].map((n) => makeCommander(n));
    const id = createSession(db, candidates, "test", "duel");
    let info = getSession(db, id);
    for (let i = 0; i < info.targetRounds; i++) {
      recordPick(db, id, "a", "b");
    }
    info = getSession(db, id);
    expect(info.status).toBe("complete");
    expect(nextPairing(db, id)).toBeNull();
  });
});

describe("bracket sessions", () => {
  let db: ReturnType<typeof connect>;
  beforeEach(() => {
    db = connect(":memory:");
  });

  it("builds a full bracket tree upfront with round-1 fully seeded", () => {
    const candidates = ["a", "b", "c", "d", "e", "f", "g", "h"].map((n) => makeCommander(n));
    const id = createSession(db, candidates, "test", "bracket");
    const bracket = getBracket(db, id);
    expect(bracket.rounds).toHaveLength(3); // log2(8)
    expect(bracket.rounds[0]).toHaveLength(4);
    expect(bracket.rounds[0].every((m) => m.seedA !== null && m.seedB !== null)).toBe(true);
    expect(bracket.rounds[1].every((m) => m.seedA === null && m.seedB === null)).toBe(true);
    expect(bracket.champion).toBeNull();
  });

  it("plays out a full bracket to a champion", () => {
    const candidates = ["a", "b", "c", "d"].map((n) => makeCommander(n));
    const id = createSession(db, candidates, "test", "bracket");
    let match = nextBracketMatch(db, id);
    while (match) {
      const [, , seedA, seedB] = match;
      recordBracketPick(db, id, seedA, seedB);
      match = nextBracketMatch(db, id);
    }
    const info = getSession(db, id);
    expect(info.status).toBe("complete");
    const bracket = getBracket(db, id);
    expect(bracket.champion).not.toBeNull();
  });
});
