import type { CandidateDetail } from "@commander-hq/shared";
import { BRACKET_LABELS } from "../constants";
import { ManaCost, Pips } from "./Pips";

// Target width for a single card face -- each image renders at (up to)
// this size regardless of how many faces this commander has, so a
// plain 1-image commander doesn't balloon to fill the whole card-btn
// while a 2-image commander's faces stay small by comparison.
const CARD_ART_TARGET_WIDTH = 210;
const CARD_ART_GAP = 1;

export function CommanderCardContent({ c }: { c: CandidateDetail }) {
  const count = c.imageUrls?.length ?? 0;
  const maxWidth = count * CARD_ART_TARGET_WIDTH + Math.max(0, count - 1) * CARD_ART_GAP;

  return (
    <>
      {count > 0 && (
        <div className="card-art-group" style={{ maxWidth }}>
          {c.imageUrls.map((url, i) => (
            <img key={i} className="card-art" src={url} alt="" loading="lazy" onError={(e) => e.currentTarget.remove()} />
          ))}
        </div>
      )}
      <div className="card-top">
        <div className="card-name">{c.name}</div>
        <Pips colors={c.colorIdentity} />
      </div>
      {c.manaCost ? <ManaCost manaCost={c.manaCost} /> : !c.manaCost && c.typeLine ? <div className="type-line">{c.typeLine}</div> : null}
      <div className="card-stats">
        <span>
          Decks <b>{c.numDecks.toLocaleString()}</b>
        </span>
      </div>
      {c.themes && c.themes.length > 0 && (
        <div className="theme-tags">
          {c.themes.map((t) => (
            <span className="tag" key={t}>
              {t}
            </span>
          ))}
        </div>
      )}
      {c.rank ? <span className="tag rank-tag">#{c.rank} on this page</span> : null}
      {c.powerLevel ? (
        <span className="tag power-tag">
          Bracket {c.powerLevel} · {BRACKET_LABELS[c.powerLevel]}
        </span>
      ) : null}
    </>
  );
}
