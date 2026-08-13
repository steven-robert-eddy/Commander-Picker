import { Router } from "express";
import * as favoritesDomain from "../domain/favorites.js";
import { SessionError } from "../db/sessions.js";
import { HttpError, withSessionsDb } from "../requestDb.js";
import { favoriteStatusBodySchema } from "../validation.js";

export const favoritesRouter = Router();

favoritesRouter.put("/favorites", (req, res) => {
  const body = favoriteStatusBodySchema.parse(req.body);
  withSessionsDb((db) => {
    try {
      res.json(favoritesDomain.setFavoriteStatus(db, body.commanderName, body.status));
    } catch (exc) {
      if (exc instanceof SessionError) throw new HttpError(422, exc.message);
      throw exc;
    }
  });
});

// commanderName is a query param, not a path segment -- several real
// commanders have "/" in their name (Partner pairs), which a path
// segment can't reliably round-trip even percent-encoded.
favoritesRouter.delete("/favorites", (req, res) => {
  const commanderName = String(req.query.commanderName ?? "");
  withSessionsDb((db) => {
    favoritesDomain.clearFavorite(db, commanderName);
    res.json({ ok: true });
  });
});
