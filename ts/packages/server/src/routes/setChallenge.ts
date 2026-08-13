import { Router } from "express";
import { SetChallengeEntry } from "@commander-hq/shared";
import * as pool from "../domain/pool.js";
import * as setChallengeDomain from "../domain/setChallenge.js";
import { SessionError } from "../db/sessions.js";
import { HttpError, withCatalogDb, withSessionsDb } from "../requestDb.js";
import { challengeCommanderBodySchema as setChallengeCommanderBodySchema, challengeStatusBodySchema as setChallengeStatusBodySchema } from "../validation.js";

export const setChallengeRouter = Router();

function knownSetsOr503() {
  return withCatalogDb((db) => pool.listKnownSets(db));
}

function enrichSetChallengeEntries(entries: SetChallengeEntry[]): SetChallengeEntry[] {
  const allNames = [...new Set(entries.flatMap((e) => e.commanders.map((c) => c.name)))];
  let imagesByName = new Map<string, { imageUrls: string[]; colorIdentity: string }>();
  if (allNames.length > 0) {
    try {
      imagesByName = withCatalogDb((db) => pool.commanderImagesByName(db, allNames));
    } catch (exc) {
      if (!(exc instanceof HttpError)) throw exc;
    }
  }
  return entries.map((e) => ({
    ...e,
    commanders: e.commanders.map((c) => {
      const info = imagesByName.get(c.name);
      return { ...c, imageUrls: info?.imageUrls ?? [], colorIdentity: info?.colorIdentity ?? null };
    }),
  }));
}

function withSessionErrorAs422(fn: () => void): void {
  try {
    fn();
  } catch (exc) {
    if (exc instanceof SessionError) throw new HttpError(422, exc.message);
    throw exc;
  }
}

setChallengeRouter.get("/set-challenge", (_req, res) => {
  const knownSets = knownSetsOr503();
  withSessionsDb((db) => res.json({ entries: enrichSetChallengeEntries(setChallengeDomain.getTracker(db, knownSets)) }));
});

setChallengeRouter.put("/set-challenge/:slug", (req, res) => {
  const body = setChallengeStatusBodySchema.parse(req.body);
  const knownSets = knownSetsOr503();
  withSessionsDb((db) => {
    withSessionErrorAs422(() =>
      res.json(setChallengeDomain.setStatus(db, knownSets, req.params.slug, body.status, body.notes ?? null))
    );
  });
});

setChallengeRouter.post("/set-challenge/:slug/commanders", (req, res) => {
  const body = setChallengeCommanderBodySchema.parse(req.body);
  const knownSets = knownSetsOr503();
  withSessionsDb((db) => {
    withSessionErrorAs422(() => res.json(setChallengeDomain.addCommander(db, knownSets, req.params.slug, body.commanderName)));
  });
});

setChallengeRouter.delete("/set-challenge/:slug/commanders", (req, res) => {
  const commanderName = String(req.query.commanderName ?? "");
  const knownSets = knownSetsOr503();
  withSessionsDb((db) => {
    withSessionErrorAs422(() => res.json(setChallengeDomain.removeCommander(db, knownSets, req.params.slug, commanderName)));
  });
});

setChallengeRouter.post("/set-challenge/:slug/commanders/choose", (req, res) => {
  const body = setChallengeCommanderBodySchema.parse(req.body);
  const knownSets = knownSetsOr503();
  withSessionsDb((db) => {
    withSessionErrorAs422(() => res.json(setChallengeDomain.chooseCommander(db, knownSets, req.params.slug, body.commanderName)));
  });
});

/** Scoped to commanders actually in this set, unlike /api/commanders/search's whole-catalog search. */
setChallengeRouter.get("/set-challenge/:slug/commanders/search", (req, res) => {
  const q = String(req.query.q ?? "");
  if (q.length < 1) {
    res.status(422).json({ error: "q is required" });
    return;
  }
  const limit = Math.min(50, Math.max(1, Number(req.query.limit ?? 20)));
  withCatalogDb((db) => res.json({ results: pool.searchCommandersInSet(db, req.params.slug, q, limit) }));
});
