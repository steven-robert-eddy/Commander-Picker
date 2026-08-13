import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Deck } from "@commander-hq/shared";
import { api } from "../api/client";
import { CommanderSearchBox } from "../components/CommanderSearchBox";
import { Pips } from "../components/Pips";

interface ParticipantRow {
  playerName: string;
  deckId: string;
  isWinner: boolean;
}

function newRow(): ParticipantRow {
  return { playerName: "", deckId: "", isWinner: false };
}

function deckRow(d: Deck, onToggleArchive: (d: Deck) => void) {
  const pips = d.colorIdentity ? (
    <div className="rank-name-line">
      <Pips colors={d.colorIdentity} />
      <div className="rank-name">{d.name}</div>
    </div>
  ) : (
    d.name
  );
  const meta = [`${Math.round(d.rating)} rating`, `${d.gamesPlayed} game${d.gamesPlayed === 1 ? "" : "s"}`, d.ownerName ? `owned by ${d.ownerName}` : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className={`session-row ${d.archived ? "pod-archived-row" : ""}`} key={d.id}>
      <div className="session-info">
        <div className="session-desc">{pips}</div>
        <div className="session-meta">{meta}</div>
      </div>
      <button type="button" className="ghost-btn" onClick={() => onToggleArchive(d)}>
        {d.archived ? "Unarchive" : "Archive"}
      </button>
    </div>
  );
}

export function PodScreen() {
  const queryClient = useQueryClient();
  const decksQuery = useQuery({ queryKey: ["pod-decks"], queryFn: api.listDecks });
  const playersQuery = useQuery({ queryKey: ["pod-players"], queryFn: api.listPlayers });
  const gamesQuery = useQuery({ queryKey: ["pod-games"], queryFn: () => api.listPodGames() });

  const decks = decksQuery.data?.decks ?? [];
  const activeDecks = decks.filter((d) => !d.archived);
  const archivedDecks = decks.filter((d) => d.archived);

  const [participants, setParticipants] = useState<ParticipantRow[]>([newRow(), newRow()]);
  const [notes, setNotes] = useState("");
  const [logError, setLogError] = useState<string | null>(null);

  const [deckName, setDeckName] = useState("");
  const [deckCommanderInput, setDeckCommanderInput] = useState("");
  const [deckCommander, setDeckCommander] = useState<{ name: string; colorIdentity: string } | null>(null);
  const [deckOwner, setDeckOwner] = useState("");
  const [deckError, setDeckError] = useState<string | null>(null);

  function invalidatePod() {
    queryClient.invalidateQueries({ queryKey: ["pod-decks"] });
    queryClient.invalidateQueries({ queryKey: ["pod-players"] });
    queryClient.invalidateQueries({ queryKey: ["pod-games"] });
  }

  function updateParticipant(i: number, patch: Partial<ParticipantRow>) {
    setParticipants((prev) => prev.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  }

  function setWinner(i: number) {
    setParticipants((prev) => prev.map((p, idx) => ({ ...p, isWinner: idx === i })));
  }

  function removeParticipant(i: number) {
    setParticipants((prev) => prev.filter((_, idx) => idx !== i));
  }

  async function submitLogGame() {
    setLogError(null);
    if (participants.some((p) => !p.playerName.trim())) {
      setLogError("Every player needs a name.");
      return;
    }
    if (participants.some((p) => !p.deckId)) {
      setLogError("Every player needs a deck -- register one below if needed.");
      return;
    }
    if (!participants.some((p) => p.isWinner)) {
      setLogError("Mark which player won.");
      return;
    }
    try {
      await api.logPodGame(
        participants.map((p) => ({ playerName: p.playerName.trim(), deckId: p.deckId, isWinner: p.isWinner })),
        notes.trim()
      );
      setNotes("");
      setParticipants([newRow(), newRow()]);
      invalidatePod();
    } catch (e) {
      setLogError((e as Error).message);
    }
  }

  async function submitRegisterDeck() {
    setDeckError(null);
    const name = deckName.trim();
    if (!name) {
      setDeckError("Deck needs a name.");
      return;
    }
    try {
      await api.registerDeck({
        name,
        commanderName: deckCommander?.name ?? null,
        colorIdentity: deckCommander?.colorIdentity ?? null,
        ownerName: deckOwner.trim() || null,
      });
      setDeckName("");
      setDeckCommanderInput("");
      setDeckCommander(null);
      setDeckOwner("");
      invalidatePod();
    } catch (e) {
      setDeckError((e as Error).message);
    }
  }

  async function toggleArchive(d: Deck) {
    try {
      if (d.archived) await api.unarchiveDeck(d.id);
      else await api.archiveDeck(d.id);
      invalidatePod();
    } catch (e) {
      window.alert((e as Error).message);
    }
  }

  async function deleteLastGame() {
    const confirmed = window.confirm("Delete the most recently logged game and revert its rating changes?");
    if (!confirmed) return;
    try {
      await api.deleteLastPodGame();
      invalidatePod();
    } catch (e) {
      window.alert((e as Error).message);
    }
  }

  const games = gamesQuery.data?.games ?? [];
  const players = playersQuery.data?.players ?? [];

  return (
    <section id="screen-pod">
      <p className="lede">
        Log real games with your playgroup — every game updates two separate Elo ratings: one for each player, one for each
        deck. Decks are registered once and reused across games.
      </p>

      <div className="panel">
        <div className="filter-label">Log a game</div>
        <div>
          {participants.map((p, i) => (
            <div className="pod-participant-row" key={i}>
              <input
                type="text"
                className="num-input pod-participant-name"
                placeholder="Player name…"
                autoComplete="off"
                value={p.playerName}
                onChange={(e) => updateParticipant(i, { playerName: e.target.value })}
              />
              <select
                className="num-input pod-participant-deck"
                value={p.deckId}
                onChange={(e) => updateParticipant(i, { deckId: e.target.value })}
              >
                <option value="">{activeDecks.length ? "Select a deck…" : "No active decks -- register one below"}</option>
                {activeDecks.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
              <label className="pod-winner-label">
                <input type="radio" name="pod-winner" checked={p.isWinner} onChange={() => setWinner(i)} /> Won
              </label>
              <button
                type="button"
                className="ghost-btn pod-participant-remove"
                disabled={participants.length <= 2}
                onClick={() => removeParticipant(i)}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
        <button className="ghost-btn" type="button" onClick={() => setParticipants((prev) => [...prev, newRow()])}>
          + Add player
        </button>
        <input
          type="text"
          className="num-input"
          placeholder="Notes (optional)"
          autoComplete="off"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
        {logError && <div className="error-note">{logError}</div>}
        <button className="start-btn" type="button" onClick={submitLogGame}>
          Log game
        </button>
      </div>

      <div className="panel">
        <div className="filter-label">Register a deck</div>
        <input
          type="text"
          className="num-input"
          placeholder="Deck name…"
          autoComplete="off"
          value={deckName}
          onChange={(e) => setDeckName(e.target.value)}
        />
        <CommanderSearchBox
          search={(q) => api.searchCommanders(q)}
          placeholder="Commander (optional)…"
          clearOnPick={false}
          inputValue={deckCommanderInput}
          onInputValueChange={(v) => {
            setDeckCommanderInput(v);
            setDeckCommander(null);
          }}
          onPick={(r) => {
            setDeckCommander({ name: r.name, colorIdentity: r.colorIdentity });
            setDeckCommanderInput(r.name);
          }}
        />
        <input
          type="text"
          className="num-input"
          placeholder="Owner (optional)…"
          autoComplete="off"
          value={deckOwner}
          onChange={(e) => setDeckOwner(e.target.value)}
        />
        {deckError && <div className="error-note">{deckError}</div>}
        <button className="ghost-btn" type="button" onClick={submitRegisterDeck}>
          Add deck
        </button>
      </div>

      <div className="filter-label">Decks</div>
      <div className="panel">
        {decks.length === 0 ? (
          <div className="spinner-note">No decks registered yet -- add one above.</div>
        ) : (
          <>
            {activeDecks.map((d) => deckRow(d, toggleArchive))}
            {archivedDecks.map((d) => deckRow(d, toggleArchive))}
          </>
        )}
      </div>

      <div className="filter-label">Players</div>
      <div className="panel">
        {players.length === 0 ? (
          <div className="spinner-note">No games logged yet -- log one above.</div>
        ) : (
          players.map((p) => (
            <div className="session-row" key={p.name}>
              <div className="session-info">
                <div className="session-desc">{p.name}</div>
                <div className="session-meta">
                  {Math.round(p.rating)} rating · {p.gamesPlayed} game{p.gamesPlayed === 1 ? "" : "s"}
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="filter-label">Recent games</div>
      <div className="panel">
        {games.length === 0 ? (
          <div className="spinner-note">No games logged yet.</div>
        ) : (
          games.map((g, i) => (
            <div className="pod-game-row" key={g.id}>
              <div className="session-meta">
                {new Date(g.createdAt * 1000).toLocaleString()}
                {g.notes ? ` — ${g.notes}` : ""}
              </div>
              <div className="pod-game-participants">
                {g.participants.map((p) => (
                  <div className={`pod-game-participant ${p.isWinner ? "pod-winner" : ""}`} key={p.playerName}>
                    {p.isWinner ? "🏆 " : ""}
                    {p.playerName} — {p.deckName}
                  </div>
                ))}
              </div>
              {i === 0 && (
                <button type="button" className="ghost-btn danger-btn pod-delete-last-btn" onClick={deleteLastGame}>
                  Delete this game
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
