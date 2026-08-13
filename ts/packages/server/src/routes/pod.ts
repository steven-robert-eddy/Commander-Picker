import { Router } from "express";
import { Deck } from "@commander-hq/shared";
import * as pool from "../domain/pool.js";
import * as podsDomain from "../domain/pods.js";
import { SessionError } from "../db/sessions.js";
import { HttpError, withCatalogDb, withSessionsDb } from "../requestDb.js";
import { logPodGameBodySchema, registerDeckBodySchema } from "../validation.js";

export const podRouter = Router();

/** Attach imageUrls to each deck, best-effort against the catalog (degrades to no art, not an error). */
function enrichDecks(decks: Deck[]): Deck[] {
  const names = [...new Set(decks.map((d) => d.commanderName).filter((n): n is string => Boolean(n)))];
  let imagesByName = new Map<string, { imageUrls: string[]; colorIdentity: string }>();
  if (names.length > 0) {
    try {
      imagesByName = withCatalogDb((db) => pool.commanderImagesByName(db, names));
    } catch (exc) {
      if (!(exc instanceof HttpError)) throw exc;
    }
  }
  return decks.map((d) => ({ ...d, imageUrls: imagesByName.get(d.commanderName ?? "")?.imageUrls ?? [] }));
}

podRouter.get("/pod/players", (_req, res) => {
  withSessionsDb((db) => res.json({ players: podsDomain.listPlayers(db) }));
});

podRouter.get("/pod/decks", (_req, res) => {
  withSessionsDb((db) => res.json({ decks: enrichDecks(podsDomain.listDecks(db)) }));
});

podRouter.post("/pod/decks", (req, res) => {
  const body = registerDeckBodySchema.parse(req.body);
  withSessionsDb((db) => {
    try {
      const deck = podsDomain.registerDeck(db, body.name, {
        commanderName: body.commanderName ?? null,
        colorIdentity: body.colorIdentity ?? null,
        ownerName: body.ownerName ?? null,
      });
      res.json(enrichDecks([deck])[0]);
    } catch (exc) {
      if (exc instanceof SessionError) throw new HttpError(422, exc.message);
      throw exc;
    }
  });
});

podRouter.post("/pod/decks/:deckId/archive", (req, res) => {
  withSessionsDb((db) => {
    try {
      res.json(enrichDecks([podsDomain.archiveDeck(db, req.params.deckId)])[0]);
    } catch (exc) {
      if (exc instanceof SessionError) throw new HttpError(404, exc.message);
      throw exc;
    }
  });
});

podRouter.post("/pod/decks/:deckId/unarchive", (req, res) => {
  withSessionsDb((db) => {
    try {
      res.json(enrichDecks([podsDomain.unarchiveDeck(db, req.params.deckId)])[0]);
    } catch (exc) {
      if (exc instanceof SessionError) throw new HttpError(404, exc.message);
      throw exc;
    }
  });
});

podRouter.get("/pod/games", (req, res) => {
  const limit = req.query.limit ? Math.min(200, Math.max(1, Number(req.query.limit))) : null;
  withSessionsDb((db) => res.json({ games: podsDomain.listPodGames(db, limit) }));
});

podRouter.post("/pod/games", (req, res) => {
  const body = logPodGameBodySchema.parse(req.body);
  withSessionsDb((db) => {
    try {
      const game = podsDomain.logPodGame(
        db,
        body.participants.map((p) => ({ playerName: p.playerName, deckId: p.deckId, isWinner: p.isWinner })),
        body.notes
      );
      res.json(game);
    } catch (exc) {
      if (exc instanceof SessionError) throw new HttpError(422, exc.message);
      throw exc;
    }
  });
});

podRouter.delete("/pod/games/last", (_req, res) => {
  withSessionsDb((db) => {
    try {
      podsDomain.deleteLastPodGame(db);
      res.json({ ok: true });
    } catch (exc) {
      if (exc instanceof SessionError) throw new HttpError(422, exc.message);
      throw exc;
    }
  });
});
