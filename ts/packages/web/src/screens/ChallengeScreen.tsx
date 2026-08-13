import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ChallengeEntry } from "@commander-hq/shared";
import { api } from "../api/client";
import { CommanderSearchBox } from "../components/CommanderSearchBox";
import { Pips } from "../components/Pips";

function challengeDisplayName(slug: string): string {
  return slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function ChallengeRow({ entry, highlighted }: { entry: ChallengeEntry; highlighted: boolean }) {
  const queryClient = useQueryClient();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (highlighted && ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlighted]);

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["challenge"] });
  }

  return (
    <div ref={ref} className={`challenge-row ${highlighted ? "challenge-row-highlight" : ""}`}>
      <div className="challenge-row-header">
        <div className="challenge-combo">
          <Pips colors={entry.colors} />
          <span>{challengeDisplayName(entry.slug)}</span>
        </div>
        <select
          className="challenge-status-select"
          defaultValue={entry.status}
          onChange={async (e) => {
            try {
              await api.setChallengeStatus(entry.slug, e.target.value, entry.notes);
            } catch (err) {
              window.alert((err as Error).message);
            }
          }}
        >
          <option value="not_started">Not started</option>
          <option value="planning">Planning</option>
          <option value="building">Building</option>
          <option value="complete">Complete</option>
        </select>
      </div>
      <div className="challenge-commanders">
        {entry.commanders.map((c) => {
          const hasArt = c.imageUrls && c.imageUrls.length > 0;
          return (
            <div className={`challenge-candidate ${c.isChosen ? "chosen" : ""}`} key={c.name}>
              {hasArt && (
                <div className="challenge-candidate-thumb-group">
                  {c.imageUrls!.map((url, i) => (
                    <img key={i} className="challenge-candidate-thumb" src={url} alt="" loading="lazy" onError={(e) => e.currentTarget.remove()} />
                  ))}
                </div>
              )}
              <div className="challenge-candidate-info">
                <Pips colors={c.colorIdentity ?? ""} />
                <span className="challenge-candidate-name">{c.name}</span>
              </div>
              <div className="challenge-candidate-actions">
                <button
                  type="button"
                  className="challenge-choose-btn"
                  title="Mark as chosen"
                  onClick={async () => {
                    try {
                      await api.chooseChallengeCommander(entry.slug, c.name);
                      invalidate();
                    } catch (e) {
                      window.alert((e as Error).message);
                    }
                  }}
                >
                  {c.isChosen ? "★" : "☆"}
                </button>
                <button
                  type="button"
                  className="challenge-remove-btn"
                  title="Remove"
                  onClick={async () => {
                    try {
                      await api.removeChallengeCommander(entry.slug, c.name);
                      invalidate();
                    } catch (e) {
                      window.alert((e as Error).message);
                    }
                  }}
                >
                  ✕
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ChallengeScreen() {
  const { data, isLoading, error } = useQuery({ queryKey: ["challenge"], queryFn: api.getChallenge });
  const queryClient = useQueryClient();
  const [highlightSlug, setHighlightSlug] = useState<string | null>(null);

  useEffect(() => {
    if (!highlightSlug) return;
    const t = setTimeout(() => setHighlightSlug(null), 1500);
    return () => clearTimeout(t);
  }, [highlightSlug]);

  return (
    <section id="screen-challenge">
      <p className="lede">
        Track a deck for all 32 color-identity combinations — set each combo's status and keep a short shortlist of commanders
        you're considering for it, with one optionally marked as your pick.
      </p>
      <div className="panel">
        <div className="filter-label">Add a commander</div>
        <CommanderSearchBox
          search={(q) => api.searchCommanders(q)}
          placeholder="Search by name…"
          onPick={async (r) => {
            try {
              const entry = await api.addChallengeCommanderAuto(r.name, r.colorIdentity);
              queryClient.invalidateQueries({ queryKey: ["challenge"] });
              setHighlightSlug(entry.slug);
            } catch (e) {
              window.alert((e as Error).message);
            }
          }}
        />
      </div>
      <div className="panel">
        {isLoading && <div className="spinner-note">Loading…</div>}
        {error && <div className="error-note">{(error as Error).message}</div>}
        {data?.entries.map((entry) => (
          <ChallengeRow key={entry.slug} entry={entry} highlighted={entry.slug === highlightSlug} />
        ))}
      </div>
    </section>
  );
}
