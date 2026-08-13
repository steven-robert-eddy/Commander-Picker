import type Database from "better-sqlite3";
import * as catalog from "./db/catalog.js";
import * as sessionsDb from "./db/sessions.js";

/** An error carrying an explicit HTTP status, for the app-level error handler. */
export class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Open a catalog.db connection for the duration of `fn`, mapping a missing DB to a 503. */
export function withCatalogDb<T>(fn: (db: Database.Database) => T): T {
  let db: Database.Database;
  try {
    db = catalog.connect();
  } catch (exc) {
    if (exc instanceof catalog.DbError) throw new HttpError(503, exc.message);
    throw exc;
  }
  try {
    return fn(db);
  } finally {
    db.close();
  }
}

/** Open a sessions.db connection for the duration of `fn`. */
export function withSessionsDb<T>(fn: (db: Database.Database) => T): T {
  const db = sessionsDb.connect();
  try {
    return fn(db);
  } finally {
    db.close();
  }
}
