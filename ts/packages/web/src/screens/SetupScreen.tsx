import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { ColorMode, FiltersBody, SearchResult, SessionMode, ThemesMode } from "@commander-hq/shared";
import { api } from "../api/client";
import { ColorChips, SegmentedToggle } from "../components/ColorChips";
import { CommanderSearchBox } from "../components/CommanderSearchBox";
import { Pips } from "../components/Pips";

const MIN_POOL_SIZE = 4; // must match server pool.DEFAULT_MIN_POOL_SIZE
const BRACKET_SIZES = [4, 8, 16, 32, 64];
const DEFAULT_POOL_SIZE = 10;

function targetRoundEstimate(n: number): number {
  if (n <= 1) return 0;
  return Math.max(1, Math.round(n * Math.log2(n)));
}

function humanizeThemeSlug(slug: string): string {
  if (slug === "plus-1-plus-1-counters") return "+1/+1 Counters";
  return slug
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function SetupScreen() {
  const navigate = useNavigate();

  const [activeColors, setActiveColors] = useState<Set<string>>(new Set());
  const [colorMode, setColorMode] = useState<ColorMode>("subset");
  const [activeThemes, setActiveThemes] = useState<Set<string>>(new Set());
  const [themeMode, setThemeMode] = useState<ThemesMode>("any");
  const [activeSets, setActiveSets] = useState<Set<string>>(new Set());
  const [maxDecks, setMaxDecks] = useState(10000);
  const [minDecks, setMinDecks] = useState(100);
  const [maxSalt, setMaxSalt] = useState<number | null>(null);
  const [poolSize, setPoolSize] = useState(DEFAULT_POOL_SIZE);

  const [selectedMode, setSelectedMode] = useState<SessionMode>("duel");
  const [bracketPoolSize, setBracketPoolSize] = useState<number | null>(null);
  const [poolSource, setPoolSource] = useState<"filtered" | "custom">("filtered");
  const [customList, setCustomList] = useState<SearchResult[]>([]);

  const [themeOpen, setThemeOpen] = useState(false);
  const [setOpen, setSetOpen] = useState(false);
  const [saltOpen, setSaltOpen] = useState(false);

  const [totalMatches, setTotalMatches] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [version, setVersion] = useState(0); // bump to force a preview refresh

  const themesQuery = useQuery({ queryKey: ["themes"], queryFn: api.getThemes });
  const setsQuery = useQuery({ queryKey: ["sets"], queryFn: api.getSets });
  const themeSlugs = themesQuery.data?.slugs ?? [];
  const knownSets = setsQuery.data?.sets ?? [];

  function currentFiltersBody(overrides: Partial<FiltersBody> = {}): FiltersBody {
    return {
      colors: activeColors.size ? [...activeColors].join("") : null,
      colorMode,
      maxDecks,
      minDecks,
      maxSalt,
      minSalt: null,
      maxPrice: null,
      themes: [...activeThemes],
      themesMode: themeMode,
      sets: [...activeSets],
      poolSize,
      minPoolSize: 4,
      mode: "duel",
      ...overrides,
    };
  }

  // Live pool preview -- re-runs whenever a filter, the mode, or the
  // bracket size selection changes (poolSource === "custom" computes its
  // own preview text locally instead, see below).
  useEffect(() => {
    if (poolSource === "custom") return;
    let cancelled = false;
    setErrorMsg(null);
    (async () => {
      try {
        const { totalMatches: total } = await api.pool(currentFiltersBody({ minPoolSize: 1, mode: selectedMode }));
        if (cancelled) return;
        setTotalMatches(total);
      } catch (e) {
        if (cancelled) return;
        const err = e as { status?: number; message: string };
        setErrorMsg(err.status === 503 ? "No commander data yet — run `update-data` first." : err.message);
        setTotalMatches(0);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    poolSource,
    [...activeColors].sort().join(","),
    colorMode,
    maxDecks,
    minDecks,
    maxSalt,
    [...activeThemes].sort().join(","),
    themeMode,
    [...activeSets].sort().join(","),
    poolSize,
    selectedMode,
    bracketPoolSize,
    version,
  ]);

  const isBracket = selectedMode === "bracket";
  const availableBracketSizes = new Set(BRACKET_SIZES.filter((s) => totalMatches !== null && s <= totalMatches));
  useEffect(() => {
    if (bracketPoolSize !== null && !availableBracketSizes.has(bracketPoolSize)) {
      setBracketPoolSize(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalMatches]);

  let poolCountLine2: React.ReactNode = "";
  let startDisabled = true;
  let liveError: string | null = errorMsg;

  if (poolSource === "custom") {
    if (isBracket) {
      if (BRACKET_SIZES.includes(customList.length)) {
        const rounds = Math.log2(customList.length);
        poolCountLine2 = (
          <>
            Bracket of <b>{customList.length}</b>, <b>{rounds}</b> round{rounds === 1 ? "" : "s"} to a champion
          </>
        );
        startDisabled = false;
      } else {
        liveError = `Bracket mode needs a power-of-two list size (4, 8, 16, 32, or 64) -- currently ${customList.length}.`;
      }
    } else {
      poolCountLine2 = (
        <>
          Dueling with your <b>{customList.length}</b>-commander list
        </>
      );
      if (customList.length < 2) {
        liveError = `Add at least 2 commanders to duel (${customList.length} so far).`;
      } else {
        startDisabled = false;
      }
    }
  } else if (totalMatches !== null) {
    if (isBracket) {
      if (!bracketPoolSize) {
        poolCountLine2 = "Pick a bracket size below.";
      } else if (totalMatches < bracketPoolSize) {
        liveError = `Only ${totalMatches} commander(s) match these filters -- not enough for a bracket of ${bracketPoolSize}. Loosen a filter or pick a smaller size.`;
        poolCountLine2 = (
          <>
            Bracket of <b>{bracketPoolSize}</b>
          </>
        );
      } else {
        const rounds = Math.log2(bracketPoolSize);
        poolCountLine2 = (
          <>
            Bracket of <b>{bracketPoolSize}</b>, <b>{rounds}</b> round{rounds === 1 ? "" : "s"} to a champion
          </>
        );
        startDisabled = false;
      }
    } else {
      const duelPoolSize = Math.min(totalMatches, poolSize);
      const rounds = duelPoolSize > 1 ? targetRoundEstimate(duelPoolSize) : "–";
      poolCountLine2 = (
        <>
          Dueling with up to <b>{poolSize}</b>, <b>{rounds}</b> rounds
        </>
      );
      if (totalMatches < MIN_POOL_SIZE) {
        liveError = `Need at least ${MIN_POOL_SIZE} matching commanders to duel (${totalMatches} right now) — loosen a filter.`;
      } else {
        startDisabled = false;
      }
    }
  }

  async function handleStart() {
    setStarting(true);
    setErrorMsg(null);
    try {
      let data;
      if (poolSource === "custom") {
        data = await api.createCustomSession(
          customList.map((c) => c.name),
          selectedMode
        );
      } else {
        const body = isBracket
          ? currentFiltersBody({ mode: "bracket", poolSize: bracketPoolSize ?? poolSize })
          : currentFiltersBody({ mode: "duel" });
        data = await api.createSession(body);
      }
      navigate(`/duel/${data.sessionId}`);
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  function handleReset() {
    setActiveColors(new Set());
    setColorMode("subset");
    setActiveThemes(new Set());
    setThemeMode("any");
    setActiveSets(new Set());
    setMaxDecks(10000);
    setMinDecks(100);
    setMaxSalt(null);
    setPoolSize(DEFAULT_POOL_SIZE);
    setBracketPoolSize(null);
    setSelectedMode("duel");
    setPoolSource("filtered");
    setCustomList([]);
    setThemeOpen(false);
    setSetOpen(false);
    setSaltOpen(false);
    setVersion((v) => v + 1);
  }

  function toggleColor(color: string) {
    setActiveColors((prev) => {
      const next = new Set(prev);
      if (next.has(color)) next.delete(color);
      else next.add(color);
      return next;
    });
  }

  function toggleTheme(slug: string) {
    setActiveThemes((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  }

  function toggleSet(slug: string) {
    setActiveSets((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  }

  const customNames = new Set(customList.map((c) => c.name));

  return (
    <section id="screen-intro">
      <p className="lede">
        Skip the Ur-Dragons and Atraxas — duel your way through real <strong>underbuilt</strong> EDH commanders from your
        EDHREC catalog until your favorites rise to the top.
      </p>
      <div className="panel">
        <div className="filter-label">Mode</div>
        <SegmentedToggle
          options={[
            { value: "duel" as SessionMode, label: "Duel" },
            { value: "bracket" as SessionMode, label: "Bracket" },
          ]}
          value={selectedMode}
          onChange={setSelectedMode}
        />

        <div className="filter-label">Pool source</div>
        <SegmentedToggle
          options={[
            { value: "filtered" as const, label: "Filtered" },
            { value: "custom" as const, label: "Custom list" },
          ]}
          value={poolSource}
          onChange={setPoolSource}
        />

        {poolSource === "filtered" ? (
          <div id="filter-controls">
            <div className="filter-label">Colors</div>
            <ColorChips active={activeColors} onToggle={toggleColor} />

            <div className="filter-label">Color match</div>
            <SegmentedToggle
              options={[
                { value: "subset" as ColorMode, label: "Any combo within colors" },
                { value: "exact" as ColorMode, label: "Exact colors only" },
              ]}
              value={colorMode}
              onChange={setColorMode}
            />

            <div className="filter-label">Max decks (underbuilt ceiling)</div>
            <div className="deck-range">
              <input
                type="range"
                min={100}
                max={60000}
                step={100}
                value={maxDecks}
                onChange={(e) => setMaxDecks(Number(e.target.value))}
              />
              <input
                type="number"
                className="num-input"
                min={1}
                max={1000000}
                step={1}
                value={maxDecks}
                onChange={(e) => setMaxDecks(Math.max(1, Math.floor(Number(e.target.value) || 0)))}
              />
            </div>

            <div className="filter-label">Min decks (obscurity floor)</div>
            <div className="deck-range">
              <input
                type="range"
                min={0}
                max={5000}
                step={10}
                value={minDecks}
                onChange={(e) => setMinDecks(Number(e.target.value))}
              />
              <input
                type="number"
                className="num-input"
                min={0}
                max={1000000}
                step={1}
                value={minDecks}
                onChange={(e) => setMinDecks(Math.max(0, Math.floor(Number(e.target.value) || 0)))}
              />
            </div>

            {/* Salt filtering: hidden for now, not removed -- fully built server-side, easy to bring back. */}
            <button
              className="filter-disclosure hidden"
              type="button"
              aria-expanded={saltOpen}
              onClick={() => setSaltOpen((v) => !v)}
            >
              <span className="filter-label">Max salt (avoid meta-warping)</span>
              <span className="filter-disclosure-chevron">▾</span>
            </button>
            <div className={`filter-disclosure-body ${saltOpen ? "" : "hidden"}`}>
              <div className="deck-range">
                <input
                  type="range"
                  min={0}
                  max={5}
                  step={0.1}
                  value={maxSalt ?? 5}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    setMaxSalt(v >= 5 ? null : v);
                  }}
                />
                <input
                  type="number"
                  className="num-input"
                  min={0}
                  max={10}
                  step={0.1}
                  value={maxSalt ?? 5}
                  onChange={(e) => {
                    const v = Math.max(0, Number(e.target.value) || 0);
                    setMaxSalt(v >= 5 ? null : v);
                  }}
                />
              </div>
            </div>

            <button className="filter-disclosure" type="button" aria-expanded={themeOpen} onClick={() => setThemeOpen((v) => !v)}>
              <span className="filter-label">Archetype / theme ({themeSlugs.length})</span>
              <span className="filter-disclosure-chevron">▾</span>
            </button>
            <div className={`filter-disclosure-body ${themeOpen ? "" : "hidden"}`}>
              <div className="filter-row">
                {themeSlugs.map((slug) => (
                  <button
                    key={slug}
                    type="button"
                    className="chip"
                    aria-pressed={activeThemes.has(slug)}
                    onClick={() => toggleTheme(slug)}
                  >
                    {humanizeThemeSlug(slug)}
                  </button>
                ))}
              </div>
              <div className="filter-label">Theme match</div>
              <SegmentedToggle
                options={[
                  { value: "any" as ThemesMode, label: "Any selected theme" },
                  { value: "all" as ThemesMode, label: "All selected themes" },
                ]}
                value={themeMode}
                onChange={setThemeMode}
              />
            </div>

            <button className="filter-disclosure" type="button" aria-expanded={setOpen} onClick={() => setSetOpen((v) => !v)}>
              <span className="filter-label">Set ({knownSets.length})</span>
              <span className="filter-disclosure-chevron">▾</span>
            </button>
            <div className={`filter-disclosure-body ${setOpen ? "" : "hidden"}`}>
              <div className="filter-row">
                {knownSets.map(({ slug, name }) => (
                  <button key={slug} type="button" className="chip" aria-pressed={activeSets.has(slug)} onClick={() => toggleSet(slug)}>
                    {name}
                  </button>
                ))}
              </div>
            </div>

            <div className="filter-label">{isBracket ? "Bracket size" : "Duel pool size"}</div>
            {!isBracket ? (
              <div className="pool-size-row">
                <input
                  type="number"
                  className="num-input"
                  min={4}
                  max={200}
                  step={1}
                  value={poolSize}
                  onChange={(e) => setPoolSize(Math.min(200, Math.max(4, Math.floor(Number(e.target.value) || 40))))}
                />
                <span className="pool-size-hint">candidates per session</span>
              </div>
            ) : (
              <div className="filter-row">
                {BRACKET_SIZES.map((size) => {
                  const disabled = !availableBracketSizes.has(size);
                  return (
                    <button
                      key={size}
                      type="button"
                      className={`chip ${disabled ? "chip-disabled" : ""}`}
                      disabled={disabled}
                      aria-pressed={bracketPoolSize === size}
                      onClick={() => setBracketPoolSize(size)}
                    >
                      {size}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          <div id="custom-list-controls">
            <div className="filter-label">Search commanders</div>
            <CommanderSearchBox
              search={(q) => api.searchCommanders(q)}
              onPick={(r) => setCustomList((prev) => [...prev, r])}
              isDisabled={(name) => customNames.has(name)}
              placeholder="Search by name…"
            />

            <div className="filter-label">Your list ({customList.length})</div>
            <div className="panel custom-list-panel">
              {customList.length === 0 ? (
                <div className="spinner-note">Search above and add commanders to build your list.</div>
              ) : (
                customList.map((c, i) => (
                  <div className="custom-list-row" key={c.name}>
                    <div className="custom-list-name">
                      <Pips colors={c.colorIdentity} />
                      {c.name}
                    </div>
                    <button
                      type="button"
                      className="ghost-btn custom-list-remove"
                      onClick={() => setCustomList((prev) => prev.filter((_, idx) => idx !== i))}
                    >
                      ✕ Remove
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        <div className="pool-count">
          <div>
            {poolSource === "custom" ? (
              <>
                <b>{customList.length}</b> commander(s) in your list
              </>
            ) : (
              <>
                <b>{totalMatches !== null ? totalMatches.toLocaleString() : "–"}</b> commanders match your filters
              </>
            )}
          </div>
          <div>{poolCountLine2}</div>
        </div>
        {liveError && <div className="error-note">{liveError}</div>}
        <button className="start-btn" disabled={startDisabled || starting} onClick={handleStart}>
          {isBracket ? "Start bracket" : "Start dueling"}
        </button>
        <button className="ghost-btn" type="button" onClick={handleReset}>
          Reset filters
        </button>
      </div>
    </section>
  );
}
