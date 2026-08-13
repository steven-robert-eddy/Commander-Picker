import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { ChallengeScreen } from "./screens/ChallengeScreen";
import { DuelScreen } from "./screens/DuelScreen";
import { HomeScreen } from "./screens/HomeScreen";
import { LeaderboardScreen } from "./screens/LeaderboardScreen";
import { PodScreen } from "./screens/PodScreen";
import { ResultsScreen } from "./screens/ResultsScreen";
import { SessionsScreen } from "./screens/SessionsScreen";
import { SetChallengeScreen } from "./screens/SetChallengeScreen";
import { SetupScreen } from "./screens/SetupScreen";

const PHASE_LABELS: [RegExp, string][] = [
  [/^\/$/, "Home"],
  [/^\/setup/, "Filter"],
  [/^\/duel\//, "Dueling"],
  [/^\/results\//, "Results"],
  [/^\/sessions/, "Sessions"],
  [/^\/challenge/, "32-Deck Challenge"],
  [/^\/set-challenge/, "Set Challenge"],
  [/^\/pod/, "Pod Tracker"],
  [/^\/leaderboard/, "Leaderboard"],
];

function phaseLabel(pathname: string): string {
  return PHASE_LABELS.find(([re]) => re.test(pathname))?.[1] ?? "Commander HQ";
}

export function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const isHome = location.pathname === "/";

  return (
    <main>
      <header>
        <div className="wordmark">
          Commander <em>HQ</em>
        </div>
        <div className="header-right">
          <button className={`header-home-btn ${isHome ? "hidden" : ""}`} type="button" onClick={() => navigate("/")}>
            ← Home
          </button>
          <div className="phase">{phaseLabel(location.pathname)}</div>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<HomeScreen />} />
        <Route path="/setup" element={<SetupScreen />} />
        <Route path="/duel/:sessionId" element={<DuelScreen />} />
        <Route path="/results/:sessionId" element={<ResultsScreen />} />
        <Route path="/sessions" element={<SessionsScreen />} />
        <Route path="/challenge" element={<ChallengeScreen />} />
        <Route path="/set-challenge" element={<SetChallengeScreen />} />
        <Route path="/pod" element={<PodScreen />} />
        <Route path="/leaderboard" element={<LeaderboardScreen />} />
      </Routes>

      <footer>
        Local single-user tool — no auth, no rate limiting. Data from your own <code>data/commanders.db</code>.
      </footer>
    </main>
  );
}
