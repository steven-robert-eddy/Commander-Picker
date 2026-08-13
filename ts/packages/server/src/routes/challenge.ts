import { Router } from "express";
import { ChallengeEntry, colors } from "@commander-hq/shared";
import * as challengeDomain from "../domain/challenge.js";
import * as pool from "../domain/pool.js";
import { SessionError } from "../db/sessions.js";
import { HttpError, withCatalogDb, withSessionsDb } from "../requestDb.js";
import { challengeAddByColorBodySchema, challengeCommanderBodySchema, challengeStatusBodySchema } from "../validation.js";

export const challengeRouter = Router();

/**
 * Attach imageUrls/colorIdentity to each entry's candidates, for a
 * card-art view instead of plain text. Missing/unreachable catalog data
 * degrades gracefully (no art, not an error).
 */
function enrichChallengeEntries(entries: ChallengeEntry[]): ChallengeEntry[] {
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

challengeRouter.get("/challenge", (_req, res) => {
  withSessionsDb((db) => res.json({ entries: enrichChallengeEntries(challengeDomain.getChallengeTracker(db)) }));
});

challengeRouter.put("/challenge/:slug", (req, res) => {
  const body = challengeStatusBodySchema.parse(req.body);
  withSessionsDb((db) => {
    withSessionErrorAs422(() => res.json(challengeDomain.setChallengeStatus(db, req.params.slug, body.status, body.notes ?? null)));
  });
});

challengeRouter.post("/challenge/:slug/commanders", (req, res) => {
  const body = challengeCommanderBodySchema.parse(req.body);
  withSessionsDb((db) => {
    withSessionErrorAs422(() => res.json(challengeDomain.addChallengeCommander(db, req.params.slug, body.commanderName)));
  });
});

challengeRouter.delete("/challenge/:slug/commanders", (req, res) => {
  const commanderName = String(req.query.commanderName ?? "");
  withSessionsDb((db) => {
    withSessionErrorAs422(() => res.json(challengeDomain.removeChallengeCommander(db, req.params.slug, commanderName)));
  });
});

challengeRouter.post("/challenge/:slug/commanders/choose", (req, res) => {
  const body = challengeCommanderBodySchema.parse(req.body);
  withSessionsDb((db) => {
    withSessionErrorAs422(() => res.json(challengeDomain.chooseChallengeCommander(db, req.params.slug, body.commanderName)));
  });
});

/** Add a candidate without the caller knowing which combo it belongs to -- the commander's own color identity determines that. */
challengeRouter.post("/challenge/commanders", (req, res) => {
  const body = challengeAddByColorBodySchema.parse(req.body);
  let slug: string;
  try {
    slug = colors.slugForColors(body.colorIdentity);
  } catch (exc) {
    if (exc instanceof colors.UnknownColorIdentityError) throw new HttpError(422, exc.message);
    throw exc;
  }
  withSessionsDb((db) => {
    withSessionErrorAs422(() => {
      const entry = challengeDomain.addChallengeCommander(db, slug, body.commanderName);
      res.json(entry);
    });
  });
});
