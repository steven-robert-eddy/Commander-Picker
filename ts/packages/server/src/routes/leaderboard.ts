import { Router } from "express";
import * as favoritesDomain from "../domain/favorites.js";
import * as sessionsDomain from "../domain/sessions.js";
import { withSessionsDb } from "../requestDb.js";

export const leaderboardRouter = Router();

leaderboardRouter.get("/leaderboard", (req, res) => {
  const limit = Math.min(500, Math.max(1, Number(req.query.limit ?? 100)));
  const colors = req.query.colors ? String(req.query.colors) : null;
  const colorMode = req.query.colorMode === "exact" ? "exact" : "subset";

  withSessionsDb((db) => {
    const ranked = sessionsDomain.getLeaderboard(db, { limit, colors, colorMode });
    const names = ranked.map((r) => r.name);
    const statusByName = favoritesDomain.favoritesByName(db, names);
    const leaderboard = ranked.map((r) => ({ ...r, favoriteStatus: statusByName.get(r.name) ?? null }));
    res.json({ leaderboard });
  });
});

leaderboardRouter.delete("/leaderboard", (_req, res) => {
  withSessionsDb((db) => {
    sessionsDomain.resetLeaderboard(db);
    res.json({ ok: true });
  });
});
