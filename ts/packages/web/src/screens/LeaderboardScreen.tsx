import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColorMode } from "@commander-hq/shared";
import { api } from "../api/client";
import { ColorChips, SegmentedToggle } from "../components/ColorChips";
import { RankList } from "../components/RankList";

export function LeaderboardScreen() {
  const [activeColors, setActiveColors] = useState<Set<string>>(new Set());
  const [colorMode, setColorMode] = useState<ColorMode>("subset");
  const queryClient = useQueryClient();

  const colorsParam = activeColors.size ? [...activeColors].join("") : null;
  const { data, isLoading, error } = useQuery({
    queryKey: ["leaderboard", colorsParam, colorMode],
    queryFn: () => api.leaderboard(colorsParam, colorMode),
  });

  function toggleColor(color: string) {
    setActiveColors((prev) => {
      const next = new Set(prev);
      if (next.has(color)) next.delete(color);
      else next.add(color);
      return next;
    });
  }

  function handleReset() {
    setActiveColors(new Set());
    setColorMode("subset");
  }

  async function handleResetData() {
    const confirmed = window.confirm(
      "This permanently erases every commander's all-time rating and games-played count. Past session results " +
        "themselves aren't affected -- only the all-time leaderboard built from them. This can't be undone. Continue?"
    );
    if (!confirmed) return;
    try {
      await api.resetLeaderboard();
      queryClient.invalidateQueries({ queryKey: ["leaderboard"] });
    } catch (e) {
      window.alert((e as Error).message);
    }
  }

  return (
    <section id="screen-leaderboard">
      <p className="lede">
        All-time Elo across every session ever played — each commander's rating carries forward and keeps refining the more
        it's picked, instead of resetting each session. Tap a commander to see its card(s) full size.
      </p>
      <div className="panel">
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

        <button className="ghost-btn" type="button" onClick={handleReset}>
          Reset filters
        </button>
      </div>

      {isLoading && <div className="spinner-note">Loading…</div>}
      {error && <div className="error-note">{(error as Error).message}</div>}
      {data && data.leaderboard.length === 0 && (
        <div className="panel">
          <div className="spinner-note">
            {activeColors.size ? "No commanders match that color filter yet." : "No all-time ratings yet — finish a duel session first."}
          </div>
        </div>
      )}
      {data && data.leaderboard.length > 0 && (
        <RankList
          rankings={data.leaderboard}
          statFor={(c) => {
            const games = "gamesPlayed" in c ? c.gamesPlayed : 0;
            return {
              className: "",
              content: (
                <>
                  {Math.round(c.rating)} <span style={{ opacity: 0.6 }}>({games === 1 ? "1 game" : `${games} games`})</span>
                </>
              ),
            };
          }}
        />
      )}
      <button className="ghost-btn danger-btn" type="button" onClick={handleResetData}>
        Reset all-time leaderboard…
      </button>
    </section>
  );
}
