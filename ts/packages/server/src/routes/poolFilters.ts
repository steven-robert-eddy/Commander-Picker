import type Database from "better-sqlite3";
import { Commander, PoolFilters } from "@commander-hq/shared";
import * as pool from "../domain/pool.js";
import { HttpError } from "../requestDb.js";
import { FiltersBodyInput } from "../validation.js";

export function toPoolFilters(body: FiltersBodyInput): PoolFilters {
  return {
    colors: body.colors ?? null,
    colorMode: body.colorMode,
    maxDecks: body.maxDecks ?? null,
    minDecks: body.minDecks ?? null,
    themes: body.themes,
    themesMode: body.themesMode,
    maxPrice: body.maxPrice ?? null,
    maxSalt: body.maxSalt ?? null,
    minSalt: body.minSalt ?? null,
    sets: body.sets,
  };
}

/**
 * `enforceBracketSize` forces minPoolSize up to exactly poolSize: buildPool
 * only ever *trims* a larger match set down to maxPoolSize, it never tops
 * up a smaller one, so without this a bracket could silently get created
 * with fewer candidates than requested -- a size that fails
 * elo.isValidBracketSize. Only session creation passes this -- the pool
 * preview endpoint must not, since enforcing it there would 422 on a
 * perfectly fine preview.
 */
export function buildPoolOr422(db: Database.Database, body: FiltersBodyInput, enforceBracketSize = false): Commander[] {
  const minPoolSize = enforceBracketSize ? body.poolSize : body.minPoolSize;
  try {
    return pool.buildPool(db, toPoolFilters(body), body.poolSize, minPoolSize);
  } catch (exc) {
    if (exc instanceof pool.PoolTooSmallError) throw new HttpError(422, exc.message);
    throw exc;
  }
}
