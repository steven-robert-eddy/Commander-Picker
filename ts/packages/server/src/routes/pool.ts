import { Router } from "express";
import * as pool from "../domain/pool.js";
import { withCatalogDb } from "../requestDb.js";
import { filtersBodySchema } from "../validation.js";
import { buildPoolOr422, toPoolFilters } from "./poolFilters.js";

export const poolRouter = Router();

poolRouter.post("/pool", (req, res) => {
  const body = filtersBodySchema.parse(req.body);
  withCatalogDb((db) => {
    const filters = toPoolFilters(body);
    const totalMatches = pool.countMatches(db, filters);
    const candidates = buildPoolOr422(db, body);
    res.json({ totalMatches, candidates });
  });
});
