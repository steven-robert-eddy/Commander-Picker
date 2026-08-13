import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

export function SessionsScreen() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useQuery({ queryKey: ["sessions"], queryFn: api.listSessions });

  return (
    <section id="screen-sessions">
      <p className="lede">Every picker session you've started — tap an active one to resume it, or a finished one to see its results again.</p>
      <div className="panel">
        {isLoading && <div className="spinner-note">Loading…</div>}
        {error && <div className="error-note">{(error as Error).message}</div>}
        {data && data.sessions.length === 0 && (
          <div className="spinner-note">No sessions yet — start a duel or bracket from the filter screen.</div>
        )}
        {data?.sessions.map((s) => {
          const modeLabel = s.mode === "bracket" ? "Bracket" : "Duel";
          const actionLabel = s.status === "active" ? "Resume →" : "View results →";
          return (
            <div className="session-row" key={s.id}>
              <div className="session-info">
                <div className="session-desc">{s.description || "No filters"}</div>
                <div className="session-meta">
                  {modeLabel} · {s.roundsCompleted}/{s.targetRounds} rounds · {s.poolSize} candidates · {s.status}
                </div>
              </div>
              <button
                className="ghost-btn session-action"
                type="button"
                onClick={() => navigate(s.status === "active" ? `/duel/${s.id}` : `/results/${s.id}`)}
              >
                {actionLabel}
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
