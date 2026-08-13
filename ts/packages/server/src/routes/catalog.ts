import { Router } from "express";
import * as pool from "../domain/pool.js";
import { withCatalogDb } from "../requestDb.js";

export const catalogRouter = Router();

catalogRouter.get("/themes", (_req, res) => {
  withCatalogDb((db) => res.json({ slugs: pool.listKnownThemes(db) }));
});

catalogRouter.get("/sets", (_req, res) => {
  withCatalogDb((db) => res.json({ sets: pool.listKnownSets(db) }));
});

catalogRouter.get("/commanders/search", (req, res) => {
  const q = String(req.query.q ?? "");
  if (q.length < 1) {
    res.status(422).json({ error: "q is required" });
    return;
  }
  const limit = Math.min(50, Math.max(1, Number(req.query.limit ?? 20)));
  withCatalogDb((db) => res.json({ results: pool.searchCommanders(db, q, limit) }));
});
