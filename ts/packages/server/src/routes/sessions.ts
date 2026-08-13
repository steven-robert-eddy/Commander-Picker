import { Router } from "express";
import { colors, elo, FavoriteStatus, PairingPayload, RankedCommander, SessionInfo } from "@commander-hq/shared";
import * as challengeDomain from "../domain/challenge.js";
import * as favoritesDomain from "../domain/favorites.js";
import * as pool from "../domain/pool.js";
import * as sessionsDomain from "../domain/sessions.js";
import { SessionError } from "../db/sessions.js";
import { HttpError, withCatalogDb, withSessionsDb } from "../requestDb.js";
import { customSessionBodySchema, filtersBodySchema, pickBodySchema } from "../validation.js";
import { buildPoolOr422, toPoolFilters } from "./poolFilters.js";
import type Database from "better-sqlite3";

export const sessionsRouter = Router();

function pairingPayload(db: Database.Database, sessionId: string): PairingPayload | null {
  const info = sessionsDomain.getSession(db, sessionId);
  if (info.mode === "bracket") return bracketPairingPayload(db, sessionId, info);

  const pair = sessionsDomain.nextPairing(db, sessionId);
  if (!pair) return null;
  const details = sessionsDomain.getCandidates(db, sessionId);
  return {
    round: info.roundsCompleted + 1,
    targetRounds: info.targetRounds,
    candidates: [details.get(pair[0])!, details.get(pair[1])!],
  };
}

function bracketPairingPayload(db: Database.Database, sessionId: string, info: SessionInfo): PairingPayload | null {
  const match = sessionsDomain.nextBracketMatch(db, sessionId);
  if (!match) return null;
  const [roundNum, , seedA, seedB] = match;
  const details = sessionsDomain.getCandidates(db, sessionId);
  return {
    round: roundNum,
    targetRounds: info.targetRounds,
    roundLabel: elo.bracketRoundLabel(roundNum, info.targetRounds),
    candidates: [details.get(seedA)!, details.get(seedB)!],
  };
}

function challengeSlugForName(rankings: RankedCommander[], name: string | null): string | null {
  if (name === null) return null;
  const match = rankings.find((r) => r.name === name);
  if (!match) return null;
  try {
    return challengeDomain.challengeSlugForCommander(match.colorIdentity);
  } catch (exc) {
    if (exc instanceof colors.UnknownColorIdentityError) return null;
    throw exc;
  }
}

function enrichFavorites<T extends { name: string }>(
  db: Database.Database,
  rows: T[]
): (T & { favoriteStatus: FavoriteStatus | null })[] {
  const statusByName = favoritesDomain.favoritesByName(
    db,
    rows.map((r) => r.name)
  );
  return rows.map((r) => ({ ...r, favoriteStatus: statusByName.get(r.name) ?? null }));
}

function withSessionErrorAs(status: number, fn: () => void): void {
  try {
    fn();
  } catch (exc) {
    if (exc instanceof SessionError) throw new HttpError(status, exc.message);
    throw exc;
  }
}

sessionsRouter.post("/sessions", (req, res) => {
  const body = filtersBodySchema.parse(req.body);
  if (body.mode === "bracket" && !elo.isValidBracketSize(body.poolSize)) {
    throw new HttpError(422, `Bracket mode needs poolSize to be a power of two (4, 8, 16, ...) -- got ${body.poolSize}.`);
  }

  const candidates = withCatalogDb((db) => buildPoolOr422(db, body, body.mode === "bracket"));

  withSessionsDb((db) => {
    const description = pool.describeFilters(toPoolFilters(body));
    const sessionId = sessionsDomain.createSession(db, candidates, description, body.mode);
    const info = sessionsDomain.getSession(db, sessionId);
    const pairing = pairingPayload(db, sessionId);
    res.json({ sessionId, info, pairing });
  });
});

sessionsRouter.post("/sessions/custom", (req, res) => {
  const body = customSessionBodySchema.parse(req.body);
  if (body.mode === "bracket" && !elo.isValidBracketSize(body.names.length)) {
    throw new HttpError(
      422,
      `Bracket mode needs a custom list size that's a power of two (4, 8, 16, ...) -- got ${body.names.length}.`
    );
  }

  const candidates = withCatalogDb((db) => {
    try {
      return pool.commandersByNames(db, body.names);
    } catch (exc) {
      if (exc instanceof pool.CommanderLookupError) throw new HttpError(422, exc.message);
      throw exc;
    }
  });

  withSessionsDb((db) => {
    const description = `Custom list (${candidates.length} commanders)`;
    const sessionId = sessionsDomain.createSession(db, candidates, description, body.mode);
    const info = sessionsDomain.getSession(db, sessionId);
    const pairing = pairingPayload(db, sessionId);
    res.json({ sessionId, info, pairing });
  });
});

sessionsRouter.get("/sessions", (_req, res) => {
  withSessionsDb((db) => res.json({ sessions: sessionsDomain.listSessions(db) }));
});

sessionsRouter.get("/sessions/:id", (req, res) => {
  withSessionsDb((db) => {
    withSessionErrorAs(404, () => res.json(sessionsDomain.getSession(db, req.params.id)));
  });
});

sessionsRouter.get("/sessions/:id/pairing", (req, res) => {
  withSessionsDb((db) => {
    withSessionErrorAs(404, () => {
      sessionsDomain.getSession(db, req.params.id);
      res.json(pairingPayload(db, req.params.id));
    });
  });
});

sessionsRouter.post("/sessions/:id/pick", (req, res) => {
  const body = pickBodySchema.parse(req.body);
  withSessionsDb((db) => {
    withSessionErrorAs(400, () => {
      const info = sessionsDomain.getSession(db, req.params.id);
      if (info.mode === "bracket") {
        sessionsDomain.recordBracketPick(db, req.params.id, body.winner, body.loser);
      } else {
        sessionsDomain.recordPick(db, req.params.id, body.winner, body.loser);
      }
      res.json(pairingPayload(db, req.params.id));
    });
  });
});

sessionsRouter.post("/sessions/:id/undo", (req, res) => {
  withSessionsDb((db) => {
    withSessionErrorAs(400, () => {
      sessionsDomain.undoLastPick(db, req.params.id);
      res.json(pairingPayload(db, req.params.id));
    });
  });
});

sessionsRouter.post("/sessions/:id/finish", (req, res) => {
  withSessionsDb((db) => {
    withSessionErrorAs(404, () => {
      const info = sessionsDomain.getSession(db, req.params.id);
      if (info.mode === "bracket") {
        throw new HttpError(400, "Bracket sessions can't be finished early -- there's no partial champion, play out the remaining matches.");
      }
      sessionsDomain.finishSession(db, req.params.id);
      const rankings = sessionsDomain.getRankings(db, req.params.id);
      const winnerName = rankings[0]?.name ?? null;
      res.json({
        rankings: enrichFavorites(db, rankings),
        winnerChallengeSlug: challengeSlugForName(rankings, winnerName),
      });
    });
  });
});

sessionsRouter.get("/sessions/:id/results", (req, res) => {
  withSessionsDb((db) => {
    withSessionErrorAs(404, () => {
      sessionsDomain.getSession(db, req.params.id);
      const rankings = sessionsDomain.getRankings(db, req.params.id);
      const winnerName = rankings[0]?.name ?? null;
      res.json({
        rankings: enrichFavorites(db, rankings),
        winnerChallengeSlug: challengeSlugForName(rankings, winnerName),
      });
    });
  });
});

sessionsRouter.get("/sessions/:id/bracket", (req, res) => {
  withSessionsDb((db) => {
    withSessionErrorAs(404, () => sessionsDomain.getSession(db, req.params.id));
    const bracket = sessionsDomain.getBracket(db, req.params.id);
    const rankings = sessionsDomain.getRankings(db, req.params.id);
    res.json({
      champion: bracket.champion,
      rounds: bracket.rounds,
      winnerChallengeSlug: challengeSlugForName(rankings, bracket.champion),
    });
  });
});
