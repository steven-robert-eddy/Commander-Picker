import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { SetChallengeEntry } from "@commander-hq/shared";
import { api } from "../api/client";
import { CommanderSearchBox } from "../components/CommanderSearchBox";
import { Pips } from "../components/Pips";

function SetChallengeRow({ entry, highlighted }: { entry: SetChallengeEntry; highlighted: boolean }) {
  const queryClient = useQueryClient();
  const ref = useRef<HTMLDivElement>(null);
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    if (highlighted && ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlighted]);

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["set-challenge"] });
  }

  return (
    <div ref={ref} className={`challenge-row ${highlighted ? "challenge-row-highlight" : ""}`}>
      <div className="challenge-row-header">
        <span>{entry.name}</span>
        <select
          className="challenge-status-select"
          defaultValue={entry.status}
          onChange={async (e) => {
            try {
              await api.setSetChallengeStatus(entry.slug, e.target.value, entry.notes);
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
                      await api.chooseSetChallengeCommander(entry.slug, c.name);
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
                      await api.removeSetChallengeCommander(entry.slug, c.name);
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
      <div className="challenge-add-row">
        <button type="button" className="ghost-btn" onClick={() => setAddOpen((v) => !v)}>
          + Add a commander from this set
        </button>
        {addOpen && (
          <CommanderSearchBox
            search={(q) => api.searchSetChallengeCommanders(entry.slug, q)}
            placeholder="Search this set…"
            onPick={async (r) => {
              try {
                await api.addSetChallengeCommander(entry.slug, r.name);
                invalidate();
              } catch (e) {
                window.alert((e as Error).message);
              }
            }}
          />
        )}
      </div>
    </div>
  );
}

export function SetChallengeScreen() {
  const { data, isLoading, error } = useQuery({ queryKey: ["set-challenge"], queryFn: api.getSetChallenge });
  const [filter, setFilter] = useState("");
  const [highlightSlug] = useState<string | null>(null);

  const entries = data?.entries ?? [];
  const filtered = filter.trim()
    ? entries.filter((e) => e.name.toLowerCase().includes(filter.trim().toLowerCase()))
    : entries;

  return (
    <section id="screen-set-challenge">
      <p className="lede">
        Track a deck for every set release with a real commander. Set each release's status and keep a short shortlist of
        commanders you're considering for it, with one optionally marked as your pick.
      </p>
      <div className="panel">
        <input
          type="text"
          className="num-input"
          placeholder="Filter by set name…"
          autoComplete="off"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <div className="panel">
        {isLoading && <div className="spinner-note">Loading…</div>}
        {error && <div className="error-note">{(error as Error).message}</div>}
        {filtered.map((entry) => (
          <SetChallengeRow key={entry.slug} entry={entry} highlighted={entry.slug === highlightSlug} />
        ))}
      </div>
    </section>
  );
}
