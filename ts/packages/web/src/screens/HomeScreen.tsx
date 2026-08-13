import { useNavigate } from "react-router-dom";

const CARDS = [
  { id: "home-picker-card", to: "/setup", title: "Pick a commander", desc: "Duel or bracket your way through EDHREC's catalog until a favorite rises to the top." },
  { id: "home-challenge-card", to: "/challenge", title: "32-deck challenge", desc: "Track a deck for every color-identity combination, colorless through five-color." },
  { id: "home-set-challenge-card", to: "/set-challenge", title: "Set challenge", desc: "Track a deck for every set release with a real commander, from the earliest precons to the newest drop." },
  { id: "home-pod-card", to: "/pod", title: "Pod tracker", desc: "Log real games with your playgroup — Elo ratings for both players and decks." },
  { id: "home-leaderboard-card", to: "/leaderboard", title: "All-time leaderboard", desc: "Cross-session Elo ratings for every commander you've ever picked." },
  { id: "home-sessions-card", to: "/sessions", title: "My sessions", desc: "Resume an active picker session, or revisit a finished one's results." },
];

export function HomeScreen() {
  const navigate = useNavigate();
  return (
    <section id="screen-home">
      <p className="lede">
        Everything for building out your Commander collection — pick a new commander, track your 32-deck challenge, log real
        pod games, or browse past sessions and the all-time leaderboard.
      </p>
      <div className="home-grid">
        {CARDS.map((c) => (
          <button key={c.to} id={c.id} className="home-card" type="button" onClick={() => navigate(c.to)}>
            <div className="home-card-title">{c.title}</div>
            <div className="home-card-desc">{c.desc}</div>
          </button>
        ))}
      </div>
    </section>
  );
}
