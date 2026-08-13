import { useEffect, useState } from "react";
import { api } from "../api/client";

function challengeDisplayName(slug: string): string {
  return slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Purely additive nudge on the results screen -- offers to add the
 * winning commander as a candidate for its color combo, never
 * overwrites/auto-chooses anything. Silently no-ops on failure or if
 * the commander's already a candidate.
 */
export function ChallengeNudge({ slug, commanderName }: { slug: string | null; commanderName: string | null }) {
  const [visible, setVisible] = useState(false);
  const [added, setAdded] = useState(false);

  useEffect(() => {
    setVisible(false);
    setAdded(false);
    if (!slug || !commanderName) return;
    let cancelled = false;
    (async () => {
      try {
        const { entries } = await api.getChallenge();
        if (cancelled) return;
        const entry = entries.find((e) => e.slug === slug);
        if (!entry || entry.commanders.some((c) => c.name === commanderName)) return;
        setVisible(true);
      } catch {
        // Non-critical -- the results screen itself still works.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug, commanderName]);

  if (!visible || !slug || !commanderName || added) return null;

  return (
    <div className="challenge-nudge">
      <span>
        Add {commanderName} as an option for {challengeDisplayName(slug)}?
      </span>
      <button
        className="ghost-btn"
        type="button"
        onClick={async () => {
          try {
            await api.addChallengeCommander(slug, commanderName);
            setAdded(true);
          } catch (e) {
            window.alert((e as Error).message);
          }
        }}
      >
        Add →
      </button>
    </div>
  );
}
