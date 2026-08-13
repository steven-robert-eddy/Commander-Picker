import { describe, expect, it } from "vitest";
import { allSlugs, COLOR_IDENTITY_BY_SLUG, slugForColors, UnknownColorIdentityError } from "./colors.js";

describe("slugForColors", () => {
  it("maps known combos regardless of order/case", () => {
    expect(slugForColors("BR")).toBe("rakdos");
    expect(slugForColors("rb")).toBe("rakdos");
    expect(slugForColors(["R", "B"])).toBe("rakdos");
  });

  it("maps mono, colorless, and five-color", () => {
    expect(slugForColors("W")).toBe("mono-white");
    expect(slugForColors("")).toBe("colorless");
    expect(slugForColors("WUBRG")).toBe("five-color");
  });

  it("throws on invalid color letters", () => {
    expect(() => slugForColors("BX")).toThrow(UnknownColorIdentityError);
  });
});

describe("allSlugs", () => {
  it("returns exactly 32 unique slugs", () => {
    const slugs = allSlugs();
    expect(slugs).toHaveLength(32);
    expect(new Set(slugs).size).toBe(32);
  });

  it("orders mono before guild before colorless last", () => {
    const slugs = allSlugs();
    expect(slugs[0]).toBe("mono-white");
    expect(slugs.at(-1)).toBe("colorless");
    expect(slugs.indexOf("azorius")).toBeGreaterThan(slugs.indexOf("mono-white"));
  });

  it("round-trips through COLOR_IDENTITY_BY_SLUG", () => {
    for (const slug of allSlugs()) {
      const colors = COLOR_IDENTITY_BY_SLUG.get(slug)!;
      expect(slugForColors(colors)).toBe(slug);
    }
  });
});
