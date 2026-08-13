/**
 * Color identity <-> EDHREC URL slug mapping.
 *
 * Ported 1:1 from `commander_picker/colors.py`. EDHREC groups its
 * commander/theme pages by color identity using slugs like `rakdos` or
 * `mono-red` in URLs such as `https://json.edhrec.com/pages/commanders/rakdos.json`.
 */

export const WUBRG = "WUBRG";

function sortColors(colors: readonly string[]): string[] {
  return [...colors].sort((a, b) => WUBRG.indexOf(a) - WUBRG.indexOf(b));
}

function key(colors: readonly string[]): string {
  return sortColors(colors).join("");
}

const GUILDS: Record<string, string> = {
  WU: "azorius",
  UB: "dimir",
  BR: "rakdos",
  RG: "gruul",
  GW: "selesnya",
  WB: "orzhov",
  UR: "izzet",
  BG: "golgari",
  RW: "boros",
  GU: "simic",
};

const TRICOLOR: Record<string, string> = {
  WUB: "esper",
  UBR: "grixis",
  BRG: "jund",
  RGW: "naya",
  GWU: "bant",
  WUR: "jeskai",
  UBG: "sultai",
  BRW: "mardu",
  RGU: "temur",
  GWB: "abzan",
};

const MONO: Record<string, string> = {
  W: "mono-white",
  U: "mono-blue",
  B: "mono-black",
  R: "mono-red",
  G: "mono-green",
};

const COLORLESS: Record<string, string> = { "": "colorless" };

const FOUR_FIVE_COLOR: Record<string, string> = {
  WUBR: "yore-tiller",
  UBRG: "glint-eye",
  BRGW: "dune-brood",
  RGWU: "ink-treader",
  GWUB: "witch-maw",
  WUBRG: "five-color",
};

function buildSlugMap(): Map<string, string> {
  const map = new Map<string, string>();
  for (const table of [COLORLESS, MONO]) {
    for (const [colors, name] of Object.entries(table)) {
      map.set(key([...colors]), name);
    }
  }
  for (const table of [GUILDS, TRICOLOR, FOUR_FIVE_COLOR]) {
    for (const [colors, name] of Object.entries(table)) {
      map.set(key([...colors]), name);
    }
  }
  return map;
}

export const SLUGS_BY_COLOR_IDENTITY = buildSlugMap();

export const COLOR_IDENTITY_BY_SLUG = new Map<string, string>(
  [...SLUGS_BY_COLOR_IDENTITY.entries()].map(([colors, slug]) => [slug, colors])
);

export class UnknownColorIdentityError extends Error {}

/** Return the EDHREC slug for a color identity. `colors` may be like "BR" or ["B","R"]. Order/case don't matter. */
export function slugForColors(colors: string | readonly string[]): string {
  const chars = (typeof colors === "string" ? colors.split("") : [...colors]).map((c) => c.toUpperCase());
  const invalid = chars.filter((c) => !WUBRG.includes(c));
  if (invalid.length > 0) {
    throw new UnknownColorIdentityError(`Not valid WUBRG colors: ${JSON.stringify([...new Set(invalid)].sort())}`);
  }
  const k = key(chars);
  const slug = SLUGS_BY_COLOR_IDENTITY.get(k);
  if (slug === undefined) {
    throw new UnknownColorIdentityError(`No EDHREC slug known for colors ${JSON.stringify(chars)}`);
  }
  return slug;
}

function orderingKey(colors: string): [number, number[]] {
  const count = colors.length === 0 ? 6 : colors.length;
  return [count, [...colors].map((c) => WUBRG.indexOf(c))];
}

function compareOrderingKeys(a: [number, number[]], b: [number, number[]]): number {
  if (a[0] !== b[0]) return a[0] - b[0];
  const [ai, bi] = [a[1], b[1]];
  for (let i = 0; i < Math.max(ai.length, bi.length); i++) {
    const av = ai[i] ?? -1;
    const bv = bi[i] ?? -1;
    if (av !== bv) return av - bv;
  }
  return 0;
}

/** All 32 color-identity slugs, ordered mono -> guild -> shard/wedge -> four-color -> five-color -> colorless. */
export function allSlugs(): string[] {
  return [...SLUGS_BY_COLOR_IDENTITY.entries()]
    .map(([colors, slug]) => ({ colors, slug, ordKey: orderingKey(colors) }))
    .sort((a, b) => compareOrderingKeys(a.ordKey, b.ordKey))
    .map((entry) => entry.slug);
}
