import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { BracketState, PairingPayload, SessionInfo } from "@commander-hq/shared";
import { api } from "../api/client";
import { BracketTree } from "../components/BracketTree";
import { CommanderCardContent } from "../components/CommanderCard";

export function DuelScreen() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();

  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [pairing, setPairing] = useState<PairingPayload | null>(null);
  const [liveBracket, setLiveBracket] = useState<BracketState | null>(null);
  const [bracketTreeOpen, setBracketTreeOpen] = useState(false);
  const [winnerSlot, setWinnerSlot] = useState<"a" | "b" | null>(null);
  const [cardsDisabled, setCardsDisabled] = useState(false);
  const [undoDisabled, setUndoDisabled] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const pickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshLiveBracket = useCallback(async () => {
    try {
      const bracket = await api.bracket(sessionId);
      setLiveBracket(bracket);
    } catch {
      // Non-critical -- the duel itself still works even if the tree strip fails to load.
    }
  }, [sessionId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const sessionInfo = await api.getSession(sessionId);
        if (cancelled) return;
        if (sessionInfo.status !== "active") {
          navigate(`/results/${sessionId}`, { replace: true });
          return;
        }
        const p = await api.getPairing(sessionId);
        if (cancelled) return;
        if (!p) {
          navigate(`/results/${sessionId}`, { replace: true });
          return;
        }
        setInfo(sessionInfo);
        setPairing(p);
        setUndoDisabled(sessionInfo.mode === "bracket" || p.round <= 1);
        if (sessionInfo.mode === "bracket") refreshLiveBracket();
      } catch (e) {
        if (!cancelled) setLoadError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, navigate, refreshLiveBracket]);

  useEffect(() => {
    return () => {
      if (pickTimer.current) clearTimeout(pickTimer.current);
    };
  }, []);

  async function pick(winnerName: string, loserName: string, slot: "a" | "b") {
    setCardsDisabled(true);
    setWinnerSlot(slot);
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const delay = reduceMotion ? 0 : 420;
    try {
      const next = await api.pick(sessionId, winnerName, loserName);
      pickTimer.current = setTimeout(() => {
        if (next) {
          setPairing(next);
          setWinnerSlot(null);
          setCardsDisabled(false);
          setUndoDisabled(info?.mode === "bracket" || next.round <= 1);
          if (info?.mode === "bracket") refreshLiveBracket();
        } else {
          navigate(`/results/${sessionId}`);
        }
      }, delay);
    } catch (e) {
      window.alert((e as Error).message);
      setCardsDisabled(false);
      setWinnerSlot(null);
    }
  }

  async function undo() {
    setUndoDisabled(true);
    try {
      const next = await api.undo(sessionId);
      if (next) {
        setPairing(next);
        setUndoDisabled(next.round <= 1);
      } else {
        navigate(`/results/${sessionId}`);
      }
    } catch (e) {
      window.alert((e as Error).message);
      setUndoDisabled(false);
    }
  }

  async function finish() {
    try {
      await api.finish(sessionId);
      navigate(`/results/${sessionId}`);
    } catch (e) {
      window.alert((e as Error).message);
    }
  }

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (!pairing || cardsDisabled) return;
      if (e.key === "1" || e.key === "ArrowLeft") {
        pick(pairing.candidates[0].name, pairing.candidates[1].name, "a");
      } else if (e.key === "2" || e.key === "ArrowRight") {
        pick(pairing.candidates[1].name, pairing.candidates[0].name, "b");
      } else if (e.key === "u" && !undoDisabled) {
        undo();
      }
    }
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pairing, cardsDisabled, undoDisabled]);

  if (loadError) {
    return (
      <section id="screen-duel">
        <div className="error-note">{loadError}</div>
      </section>
    );
  }
  if (!info || !pairing) {
    return (
      <section id="screen-duel">
        <div className="spinner-note">Loading…</div>
      </section>
    );
  }

  const isBracket = info.mode === "bracket";
  const progress = Math.min(100, ((pairing.round - 1) / Math.max(1, pairing.targetRounds)) * 100);
  const [candA, candB] = pairing.candidates;

  return (
    <section id="screen-duel">
      <div className="round-meta">
        <span>
          {isBracket ? (
            pairing.roundLabel
          ) : (
            <>
              Round <b>{pairing.round}</b> of <b>{pairing.targetRounds}</b>
            </>
          )}
        </span>
        <span>{info.poolSize} candidates</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${progress}%` }} />
      </div>

      {isBracket && (
        <>
          <button
            className="filter-disclosure"
            type="button"
            aria-expanded={bracketTreeOpen}
            aria-controls="bracket-tree-live"
            onClick={() => setBracketTreeOpen((v) => !v)}
          >
            <span className="filter-label">Bracket</span>
            <span className="filter-disclosure-chevron">▾</span>
          </button>
          <div className={bracketTreeOpen ? "" : "hidden"}>
            {liveBracket && <BracketTree rounds={liveBracket.rounds} compact />}
          </div>
        </>
      )}

      <div className="duel">
        <button
          className={`card-btn ${winnerSlot === "a" ? "winner" : winnerSlot === "b" ? "loser" : ""}`}
          disabled={cardsDisabled}
          onClick={() => pick(candA.name, candB.name, "a")}
        >
          <CommanderCardContent c={candA} />
        </button>
        <div className="medallion">vs</div>
        <button
          className={`card-btn ${winnerSlot === "b" ? "winner" : winnerSlot === "a" ? "loser" : ""}`}
          disabled={cardsDisabled}
          onClick={() => pick(candB.name, candA.name, "b")}
        >
          <CommanderCardContent c={candB} />
        </button>
      </div>

      <div className="duel-actions">
        <button className={`action-btn ${isBracket ? "hidden" : ""}`} disabled={undoDisabled} onClick={undo}>
          ← Undo
        </button>
        <span className="duel-hint">tap a card to pick (or press 1/2)</span>
        <button className={`action-btn ${isBracket ? "hidden" : ""}`} onClick={finish}>
          Finish now →
        </button>
      </div>
    </section>
  );
}
