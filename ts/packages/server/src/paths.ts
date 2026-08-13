import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** The `ts/` workspace root — three levels above `server/src` (or `server/dist`). */
export const WORKSPACE_ROOT = path.resolve(HERE, "..", "..", "..");

export const DATA_DIR = path.join(WORKSPACE_ROOT, "data");
export const EDHREC_DIR = path.join(DATA_DIR, "edhrec");
export const EDHREC_META_PATH = path.join(DATA_DIR, "edhrec_meta.json");
export const SCRYFALL_DIR = path.join(DATA_DIR, "scryfall");
export const ORACLE_CARDS_PATH = path.join(SCRYFALL_DIR, "oracle_cards.json");
export const SCRYFALL_SETS_PATH = path.join(SCRYFALL_DIR, "sets.json");
export const SCRYFALL_META_PATH = path.join(SCRYFALL_DIR, "meta.json");
export const SCRYFALL_SETS_META_PATH = path.join(SCRYFALL_DIR, "sets_meta.json");
export const CATALOG_DB_PATH = path.join(DATA_DIR, "commanders.db");
export const SESSIONS_DB_PATH = path.join(DATA_DIR, "sessions.db");
export const WEB_DIST_DIR = path.join(WORKSPACE_ROOT, "packages", "web", "dist");
