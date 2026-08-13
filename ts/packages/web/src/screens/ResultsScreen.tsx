import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { BracketState, RankedCommander, SessionInfo } from "@commander-hq/shared";
import { api } from "../api/client";
import { BracketTree } from "../components/BracketTree";
import { ChallengeNudge } from "../components/ChallengeNudge";
import { RankList } from "../components/RankList";

export function ResultsScreen() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();

  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [rankings, setRankings] = useState<RankedCommander[] | null>(null);
  const [bracket, setBracket] = useState<(BracketState & { winnerChallengeSlug: string | null }) | null>(null);
  const [winnerChallengeSlug, setWinnerChallengeSlug] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const sessionInfo = await api.getSession(sessionId);
        if (cancelled) return;
        setInfo(sessionInfo);
        if (sessionInfo.mode === "bracket") {
          const b = await api.bracket(sessionId);
          if (cancelled) return;
          setBracket(b);
        } else {
          const r = await api.results(sessionId);
          if (cancelled) return;
          setRankings(r.rankings);
          setWinnerChallengeSlug(r.winnerChallengeSlug);
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (error) {
    return (
      <section id="screen-results">
        <div className="error-note">{error}</div>
      </section>
    );
  }
  if (!info) {
    return (
      <section id="screen-results">
        <div className="spinner-note">Loading…</div>
      </section>
    );
  }

  const isBracket = info.mode === "bracket";
  const championName = isBracket ? bracket?.champion ?? null : rankings?.[0]?.name ?? null;
  const nudgeSlug = isBracket ? bracket?.winnerChallengeSlug ?? null : winnerChallengeSlug;

  return (
    <section id="screen-results">
      <p className="lede">
        {isBracket
          ? "The bracket's played out — every match also fed the all-time leaderboard below."
          : "Final standings for this run — every pick also feeds the all-time leaderboard below. Tap a commander to see its card(s) full size."}
      </p>

      <ChallengeNudge slug={nudgeSlug} commanderName={championName} />

      {isBracket ? (
        <>
          {bracket?.champion && (
            <div className="champion-banner">
              <div className="champion-label">🏆 Champion</div>
              <div className="champion-name">{bracket.champion}</div>
            </div>
          )}
          {bracket && <BracketTree rounds={bracket.rounds} compact={false} />}
        </>
      ) : (
        rankings && (
          <RankList
            rankings={rankings}
            statFor={(c) => {
              const delta = c.rating - 1000;
              const sign = delta > 0 ? "+" : "";
              return {
                className: delta > 0 ? "up" : "",
                content: (
                  <>
                    {Math.round(c.rating)} <span style={{ opacity: 0.6 }}>({sign}{Math.round(delta)})</span>
                  </>
                ),
              };
            }}
          />
        )
      )}

      <button className="again-btn" onClick={() => navigate("/setup")}>
        Duel again
      </button>
      <button className="ghost-btn" type="button" onClick={() => navigate("/leaderboard")}>
        All-time leaderboard →
      </button>
    </section>
  );
}
