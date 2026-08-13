import { describe, expect, it } from "vitest";
import {
  bracketRoundCount,
  bracketRoundLabel,
  bracketSeedOrder,
  choosePairing,
  expectedScore,
  isValidBracketSize,
  multiplayerExpectedScores,
  targetRoundCount,
  updateMultiplayerRatings,
  updateRatings,
} from "./elo.js";

describe("expectedScore", () => {
  it("is 0.5 for equal ratings", () => {
    expect(expectedScore(1000, 1000)).toBeCloseTo(0.5);
  });
});

describe("updateRatings", () => {
  it("moves winner up and loser down by equal magnitude at equal ratings", () => {
    const [winner, loser] = updateRatings(1000, 1000);
    expect(winner).toBeCloseTo(1016);
    expect(loser).toBeCloseTo(984);
  });
});

describe("multiplayer ratings", () => {
  it("expected scores sum to 1", () => {
    const scores = multiplayerExpectedScores([1000, 1100, 900, 1000]);
    expect(scores.reduce((a, b) => a + b, 0)).toBeCloseTo(1);
  });

  it("update is zero-sum across the field", () => {
    const before = [1000, 1100, 900, 1000];
    const after = updateMultiplayerRatings(before, 2);
    const beforeSum = before.reduce((a, b) => a + b, 0);
    const afterSum = after.reduce((a, b) => a + b, 0);
    expect(afterSum).toBeCloseTo(beforeSum);
  });
});

describe("targetRoundCount", () => {
  it("matches the n*log2(n) heuristic", () => {
    expect(targetRoundCount(40)).toBe(Math.max(1, Math.round(40 * Math.log2(40))));
    expect(targetRoundCount(1)).toBe(0);
    expect(targetRoundCount(0)).toBe(0);
  });
});

describe("isValidBracketSize", () => {
  it("accepts powers of two >= 4", () => {
    expect(isValidBracketSize(4)).toBe(true);
    expect(isValidBracketSize(8)).toBe(true);
    expect(isValidBracketSize(64)).toBe(true);
  });
  it("rejects everything else", () => {
    expect(isValidBracketSize(2)).toBe(false);
    expect(isValidBracketSize(3)).toBe(false);
    expect(isValidBracketSize(6)).toBe(false);
  });
});

describe("bracketRoundCount", () => {
  it("is log2(n)", () => {
    expect(bracketRoundCount(8)).toBe(3);
    expect(bracketRoundCount(64)).toBe(6);
  });
});

describe("bracketSeedOrder", () => {
  it("matches the known n=8 sequence", () => {
    expect(bracketSeedOrder(8)).toEqual([1, 8, 4, 5, 2, 7, 3, 6]);
  });
  it("matches the known n=4 sequence", () => {
    expect(bracketSeedOrder(4)).toEqual([1, 4, 2, 3]);
  });
});

describe("bracketRoundLabel", () => {
  it("labels the final, semifinal, quarterfinal, and earlier rounds", () => {
    expect(bracketRoundLabel(3, 3)).toBe("Final");
    expect(bracketRoundLabel(2, 3)).toBe("Semifinal");
    expect(bracketRoundLabel(4, 6)).toBe("Quarterfinal");
    expect(bracketRoundLabel(1, 6)).toBe("Round of 64");
  });
});

describe("choosePairing", () => {
  it("returns null with fewer than 2 candidates", () => {
    expect(choosePairing(["a"], new Map([["a", 1000]]), 0, 10, new Set())).toBeNull();
  });

  it("always returns two distinct known candidates", () => {
    const names = ["a", "b", "c", "d"];
    const ratings = new Map(names.map((n) => [n, 1000]));
    for (let i = 0; i < 50; i++) {
      const pair = choosePairing(names, ratings, i, 30, new Set());
      expect(pair).not.toBeNull();
      const [a, b] = pair!;
      expect(a).not.toBe(b);
      expect(names).toContain(a);
      expect(names).toContain(b);
    }
  });
});
