import { MANA_ORDER, MANA_SYMBOL_BASE_URL } from "../constants";

export function ColorChips({ active, onToggle }: { active: Set<string>; onToggle: (color: string) => void }) {
  return (
    <div className="filter-row">
      {MANA_ORDER.map((col) => {
        const label = col === "C" ? "Colorless" : col;
        const pressed = active.has(col);
        return (
          <button key={col} type="button" className="chip" aria-pressed={pressed} onClick={() => onToggle(col)}>
            <img className="chip-pip" src={`${MANA_SYMBOL_BASE_URL}${col}.svg`} alt="" />
            {label}
          </button>
        );
      })}
    </div>
  );
}

export function SegmentedToggle<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className="segmented-btn"
          aria-pressed={value === opt.value}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
