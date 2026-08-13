import type { ReactNode } from "react";
import type { GlobalRanking, RankedCommander } from "@commander-hq/shared";
import { BRACKET_LABELS } from "../constants";
import { FavButton } from "./FavButton";
import { useLightbox } from "./LightboxContext";
import { Pips } from "./Pips";

type RankEntry = RankedCommander | GlobalRanking;

/**
 * Shared row renderer for both session-results and the all-time
 * leaderboard -- the caller supplies `statFor` for the right-hand stat
 * column, matching core.js's renderRankList.
 */
export function RankList({
  rankings,
  statFor,
}: {
  rankings: RankEntry[];
  statFor: (c: RankEntry) => { className: string; content: ReactNode };
}) {
  const { open } = useLightbox();

  return (
    <div className="panel" id="rank-list">
      {rankings.map((c, i) => {
        const hasArt = c.imageUrls && c.imageUrls.length > 0;
        const { className, content } = statFor(c);
        const powerLevel = "powerLevel" in c ? c.powerLevel : null;
        const openThisLightbox = () =>
          open({
            imageUrls: c.imageUrls,
            name: c.name,
            edhrecUrl: c.edhrecUrl,
            favoriteStatus: c.favoriteStatus ?? null,
          });

        return (
          <div
            key={c.name}
            className={`rank-row ${i === 0 ? "top1" : ""} ${hasArt ? "has-art" : ""}`}
            tabIndex={hasArt ? 0 : undefined}
            role={hasArt ? "button" : undefined}
            onClick={hasArt ? openThisLightbox : undefined}
            onKeyDown={
              hasArt
                ? (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      openThisLightbox();
                    }
                  }
                : undefined
            }
          >
            <div className="rank-num">{i + 1}</div>
            <div className="rank-name-line">
              {hasArt && (
                <div className="rank-thumb-group">
                  {c.imageUrls.map((url, j) => (
                    <img key={j} className="rank-thumb" src={url} alt="" loading="lazy" onError={(e) => e.currentTarget.remove()} />
                  ))}
                </div>
              )}
              <Pips colors={c.colorIdentity} />
              <div className="rank-name">{c.name}</div>
              {powerLevel ? (
                <span className="tag power-tag">
                  Bracket {powerLevel} · {BRACKET_LABELS[powerLevel]}
                </span>
              ) : null}
              <FavButton commanderName={c.name} status={c.favoriteStatus ?? null} />
            </div>
            <div className={`rank-rating ${className}`}>{content}</div>
          </div>
        );
      })}
    </div>
  );
}
