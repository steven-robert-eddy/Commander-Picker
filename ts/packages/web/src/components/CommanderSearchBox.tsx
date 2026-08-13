import { useEffect, useRef, useState } from "react";
import type { SearchResult } from "@commander-hq/shared";
import { Pips } from "./Pips";

/**
 * Search-as-you-type commander autocomplete, shared by the custom-list
 * builder, the 32-deck/set challenge add flows, and the pod tracker's
 * deck-commander picker.
 */
export function CommanderSearchBox({
  search,
  onPick,
  isDisabled,
  placeholder = "Search by name…",
  clearOnPick = true,
  inputValue,
  onInputValueChange,
}: {
  search: (q: string) => Promise<{ results: SearchResult[] }>;
  onPick: (r: SearchResult) => void;
  isDisabled?: (name: string) => boolean;
  placeholder?: string;
  /** false keeps the picked name in the input (e.g. the pod deck-commander field). */
  clearOnPick?: boolean;
  inputValue?: string;
  onInputValueChange?: (value: string) => void;
}) {
  const [internalValue, setInternalValue] = useState("");
  const value = inputValue !== undefined ? inputValue : internalValue;
  const setValue = onInputValueChange ?? setInternalValue;

  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  function handleChange(q: string) {
    setValue(q);
    if (timer.current) clearTimeout(timer.current);
    const trimmed = q.trim();
    if (!trimmed) {
      setOpen(false);
      setResults(null);
      return;
    }
    timer.current = setTimeout(async () => {
      try {
        const { results: r } = await search(trimmed);
        setResults(r);
        setError(null);
        setOpen(true);
      } catch (e) {
        setError((e as Error).message);
        setOpen(true);
      }
    }, 250);
  }

  function pick(r: SearchResult) {
    if (isDisabled?.(r.name)) return;
    onPick(r);
    setOpen(false);
    setResults(null);
    if (clearOnPick) setValue("");
  }

  return (
    <div className="autocomplete-wrap">
      <input
        type="text"
        className="num-input"
        placeholder={placeholder}
        autoComplete="off"
        value={value}
        onChange={(e) => handleChange(e.target.value)}
      />
      {open && (
        <div className="autocomplete-dropdown">
          {error ? (
            <div className="spinner-note" style={{ padding: "9px 12px" }}>
              {error}
            </div>
          ) : !results || results.length === 0 ? (
            <div className="spinner-note" style={{ padding: "9px 12px" }}>
              No matches
            </div>
          ) : (
            results.map((r) => {
              const disabled = isDisabled?.(r.name) ?? false;
              return (
                <button
                  key={r.name}
                  type="button"
                  className="autocomplete-item"
                  disabled={disabled}
                  onClick={() => pick(r)}
                >
                  <Pips colors={r.colorIdentity} className="pips" />
                  <span>
                    {r.name}
                    {disabled ? " (added)" : ""}
                  </span>
                  <span className="autocomplete-item-decks">{r.numDecks.toLocaleString()} decks</span>
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
