export const MANA_SYMBOL_BASE_URL = "https://svgs.scryfall.io/card-symbols/";
export const MANA_ORDER = ["W", "U", "B", "R", "G", "C"] as const;

// WotC's official Commander Bracket names, mirroring the 1-5 scale
// db.py's _apply_commander_detail derives from EDHREC's bracket_counts.
export const BRACKET_LABELS: Record<number, string> = {
  1: "Exhibition",
  2: "Core",
  3: "Upgraded",
  4: "Optimized",
  5: "cEDH",
};
