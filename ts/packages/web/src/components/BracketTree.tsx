import type { BracketMatch } from "@commander-hq/shared";

function bracketRoundLabel(roundNum: number, totalRounds: number): string {
  const remaining = totalRounds - roundNum;
  if (remaining === 0) return "Final";
  if (remaining === 1) return "Semifinal";
  if (remaining === 2) return "Quarterfinal";
  return `Round of ${2 ** (remaining + 1)}`;
}

export function BracketTree({ rounds, compact }: { rounds: BracketMatch[][]; compact: boolean }) {
  const totalRounds = rounds.length;
  return (
    <div className={`bracket-tree ${compact ? "bracket-tree-compact" : ""}`}>
      {rounds.map((matches, i) => (
        <div className="bracket-round" key={i}>
          <div className="bracket-round-label">{bracketRoundLabel(i + 1, totalRounds)}</div>
          {matches.map((m, j) => {
            const a = m.seedA || "TBD";
            const b = m.seedB || "TBD";
            const aCls = !m.winner ? "" : m.winner === m.seedA ? "bracket-winner" : "bracket-loser";
            const bCls = !m.winner ? "" : m.winner === m.seedB ? "bracket-winner" : "bracket-loser";
            return (
              <div className="bracket-match" key={j}>
                <div className={`bracket-slot ${aCls}`}>{a}</div>
                <div className={`bracket-slot ${bCls}`}>{b}</div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
