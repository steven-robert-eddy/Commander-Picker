import { MANA_SYMBOL_BASE_URL } from "../constants";

/** Real Scryfall mana symbols for a color identity string, e.g. "BR" or "" (colorless). */
export function Pips({ colors, className = "pips" }: { colors: string | null | undefined; className?: string }) {
  const list = !colors ? ["C"] : colors.split("");
  return (
    <div className={className}>
      {list.map((c, i) => (
        <img key={`${c}-${i}`} className="pip" src={`${MANA_SYMBOL_BASE_URL}${c}.svg`} alt={c} loading="lazy" />
      ))}
    </div>
  );
}

/** Scryfall's mana-cost shorthand ("{2}{B}{R}") rendered as pip images. */
export function ManaCost({ manaCost }: { manaCost: string }) {
  const symbols = manaCost.match(/\{([^}]+)\}/g) ?? [];
  return (
    <div className="mana-cost">
      {symbols.map((s, i) => {
        const code = s.slice(1, -1);
        const filename = code.replace("/", "-");
        return (
          <img
            key={`${code}-${i}`}
            className="pip"
            src={`${MANA_SYMBOL_BASE_URL}${filename}.svg`}
            alt={code}
            loading="lazy"
            onError={(e) => e.currentTarget.remove()}
          />
        );
      })}
    </div>
  );
}
