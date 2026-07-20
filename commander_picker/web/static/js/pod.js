// Pod tracker screen -- log real multiplayer EDH games, with separate
// Elo ratings for players (freeform names, created implicitly on
// first use) and decks (a pre-registered, never-hard-deleted registry
// -- see sessions.py's pod-tracker section for the full rationale).
(function () {
  "use strict";

  const { $, api, pipsHTML, showScreen } = window.CP;

  // Decks currently available to pick for a new game -- non-archived
  // only, refreshed every time the screen's data reloads. Used to
  // populate every participant row's deck <select>.
  let activeDecks = [];

  // Set by picking a commander-search result in the register-deck
  // form; cleared whenever the input is retyped, so submitting only
  // links a commander when the typed name still matches an actual
  // pick (not a half-edited leftover from a previous search).
  let selectedDeckCommander = null;
  let deckSearchDebounceTimer = null;

  // ---- log-a-game form ----

  function participantRowHTML() {
    return `
      <div class="pod-participant-row">
        <input type="text" class="num-input pod-participant-name" placeholder="Player name…" autocomplete="off" />
        <select class="num-input pod-participant-deck"></select>
        <label class="pod-winner-label"><input type="radio" name="pod-winner" class="pod-participant-winner" /> Won</label>
        <button type="button" class="ghost-btn pod-participant-remove">✕</button>
      </div>
    `;
  }

  function populateDeckSelect(selectEl) {
    const current = selectEl.value;
    selectEl.innerHTML = activeDecks.length
      ? activeDecks.map((d) => `<option value="${d.id}">${d.name}</option>`).join("")
      : '<option value="">No active decks -- register one below</option>';
    if (current && activeDecks.some((d) => d.id === current)) selectEl.value = current;
  }

  function refreshAllDeckSelects() {
    $("pod-participants-list")
      .querySelectorAll(".pod-participant-deck")
      .forEach(populateDeckSelect);
  }

  function updateRemoveButtonsVisibility() {
    const rows = $("pod-participants-list").querySelectorAll(".pod-participant-row");
    // Need at least 2 participants to log a game (see sessions.log_pod_game) --
    // disable the last two rows' remove buttons rather than letting the
    // list shrink below that and only failing on submit.
    rows.forEach((row, i) => {
      row.querySelector(".pod-participant-remove").disabled = rows.length <= 2;
    });
  }

  function addParticipantRow() {
    const wrap = document.createElement("div");
    wrap.innerHTML = participantRowHTML();
    const row = wrap.firstElementChild;
    $("pod-participants-list").appendChild(row);
    populateDeckSelect(row.querySelector(".pod-participant-deck"));
    row.querySelector(".pod-participant-remove").addEventListener("click", () => {
      row.remove();
      updateRemoveButtonsVisibility();
    });
    updateRemoveButtonsVisibility();
  }

  function resetParticipantRows() {
    $("pod-participants-list").innerHTML = "";
    addParticipantRow();
    addParticipantRow();
  }

  async function submitLogGame() {
    const errEl = $("pod-log-error");
    errEl.classList.add("hidden");
    const rows = [...$("pod-participants-list").querySelectorAll(".pod-participant-row")];
    const participants = rows.map((row) => ({
      player_name: row.querySelector(".pod-participant-name").value.trim(),
      deck_id: row.querySelector(".pod-participant-deck").value,
      is_winner: row.querySelector(".pod-participant-winner").checked,
    }));
    if (participants.some((p) => !p.player_name)) {
      errEl.textContent = "Every player needs a name.";
      errEl.classList.remove("hidden");
      return;
    }
    if (participants.some((p) => !p.deck_id)) {
      errEl.textContent = "Every player needs a deck -- register one below if needed.";
      errEl.classList.remove("hidden");
      return;
    }
    if (!participants.some((p) => p.is_winner)) {
      errEl.textContent = "Mark which player won.";
      errEl.classList.remove("hidden");
      return;
    }
    try {
      await api("POST", "/api/pod/games", { participants, notes: $("pod-notes-input").value.trim() });
      $("pod-notes-input").value = "";
      resetParticipantRows();
      await refreshPodData();
    } catch (e) {
      errEl.textContent = e.message;
      errEl.classList.remove("hidden");
    }
  }

  // ---- register-a-deck form ----
  // Commander search reuses the exact search-as-you-type pattern
  // challenge.js/picker.js already use against GET /api/commanders/search
  // -- the only difference is a pick here fills a text field and sets
  // selectedDeckCommander rather than immediately submitting anything.

  async function searchDeckCommander() {
    const q = $("pod-deck-commander-input").value.trim();
    const resultsEl = $("pod-deck-commander-results");
    selectedDeckCommander = null; // retyping invalidates a previous pick
    if (!q) {
      resultsEl.classList.add("hidden");
      resultsEl.innerHTML = "";
      return;
    }
    try {
      const { results } = await api("GET", `/api/commanders/search?q=${encodeURIComponent(q)}`);
      if (!results.length) {
        resultsEl.innerHTML = '<div class="spinner-note" style="padding: 9px 12px;">No matches</div>';
        resultsEl.classList.remove("hidden");
        return;
      }
      resultsEl.innerHTML = results
        .map(
          (r) => `
            <button type="button" class="autocomplete-item" data-name="${r.name}" data-colors="${r.color_identity}">
              ${pipsHTML(r.color_identity)}
              <span>${r.name}</span>
            </button>
          `
        )
        .join("");
      resultsEl.querySelectorAll(".autocomplete-item").forEach((btn) => {
        btn.addEventListener("click", () => {
          selectedDeckCommander = { name: btn.dataset.name, color_identity: btn.dataset.colors };
          $("pod-deck-commander-input").value = btn.dataset.name;
          resultsEl.classList.add("hidden");
          resultsEl.innerHTML = "";
        });
      });
      resultsEl.classList.remove("hidden");
    } catch (e) {
      resultsEl.innerHTML = `<div class="spinner-note" style="padding: 9px 12px;">${e.message}</div>`;
      resultsEl.classList.remove("hidden");
    }
  }

  async function submitRegisterDeck() {
    const errEl = $("pod-deck-error");
    errEl.classList.add("hidden");
    const name = $("pod-deck-name-input").value.trim();
    if (!name) {
      errEl.textContent = "Deck needs a name.";
      errEl.classList.remove("hidden");
      return;
    }
    const owner = $("pod-deck-owner-input").value.trim();
    try {
      await api("POST", "/api/pod/decks", {
        name,
        commander_name: selectedDeckCommander ? selectedDeckCommander.name : null,
        color_identity: selectedDeckCommander ? selectedDeckCommander.color_identity : null,
        owner_name: owner || null,
      });
      $("pod-deck-name-input").value = "";
      $("pod-deck-commander-input").value = "";
      $("pod-deck-owner-input").value = "";
      selectedDeckCommander = null;
      await refreshPodData();
    } catch (e) {
      errEl.textContent = e.message;
      errEl.classList.remove("hidden");
    }
  }

  async function toggleDeckArchived(deckId, archived) {
    try {
      await api("POST", `/api/pod/decks/${encodeURIComponent(deckId)}/${archived ? "unarchive" : "archive"}`);
      await refreshPodData();
    } catch (e) {
      window.alert(e.message);
    }
  }

  // ---- rendering: decks, players, recent games ----
  // Deck/player rows reuse .session-row's flex layout (info + a
  // trailing action button) rather than .rank-row -- .rank-row's grid
  // is shaped around a rank number + art thumbnail, neither of which
  // applies here.

  function deckRowHTML(d) {
    const pips = d.color_identity ? `<div class="rank-name-line"><div class="pips">${pipsHTML(d.color_identity)}</div><div class="rank-name">${d.name}</div></div>` : d.name;
    const meta = [`${Math.round(d.rating)} rating`, `${d.games_played} game${d.games_played === 1 ? "" : "s"}`, d.owner_name ? `owned by ${d.owner_name}` : null]
      .filter(Boolean)
      .join(" · ");
    return `
      <div class="session-row ${d.archived ? "pod-archived-row" : ""}" data-id="${d.id}">
        <div class="session-info">
          <div class="session-desc">${pips}</div>
          <div class="session-meta">${meta}</div>
        </div>
        <button type="button" class="ghost-btn pod-deck-toggle-btn" data-id="${d.id}" data-archived="${d.archived ? "1" : "0"}">
          ${d.archived ? "Unarchive" : "Archive"}
        </button>
      </div>
    `;
  }

  function renderDecksList(decks) {
    const list = $("pod-decks-list");
    if (!decks.length) {
      list.innerHTML = '<div class="spinner-note">No decks registered yet -- add one above.</div>';
      return;
    }
    const active = decks.filter((d) => !d.archived);
    const archived = decks.filter((d) => d.archived);
    list.innerHTML = active.map(deckRowHTML).join("") + archived.map(deckRowHTML).join("");
    list.querySelectorAll(".pod-deck-toggle-btn").forEach((btn) => {
      btn.addEventListener("click", () => toggleDeckArchived(btn.dataset.id, btn.dataset.archived === "1"));
    });
  }

  function renderPlayersList(players) {
    const list = $("pod-players-list");
    if (!players.length) {
      list.innerHTML = '<div class="spinner-note">No games logged yet -- log one above.</div>';
      return;
    }
    list.innerHTML = players
      .map(
        (p) => `
          <div class="session-row">
            <div class="session-info">
              <div class="session-desc">${p.name}</div>
              <div class="session-meta">${Math.round(p.rating)} rating · ${p.games_played} game${p.games_played === 1 ? "" : "s"}</div>
            </div>
          </div>
        `
      )
      .join("");
  }

  function renderGamesList(games) {
    const list = $("pod-games-list");
    if (!games.length) {
      list.innerHTML = '<div class="spinner-note">No games logged yet.</div>';
      return;
    }
    list.innerHTML = games
      .map((g, i) => {
        const when = new Date(g.created_at * 1000).toLocaleString();
        const participantsHTML = g.participants
          .map((p) => `<div class="pod-game-participant ${p.is_winner ? "pod-winner" : ""}">${p.is_winner ? "🏆 " : ""}${p.player_name} — ${p.deck_name}</div>`)
          .join("");
        // Only the single most-recent game (i === 0, since list_pod_games
        // orders newest-first) gets a delete affordance -- the backend
        // only supports undoing the last game, same as undo_last_pick's
        // picker-session precedent (see sessions.delete_last_pod_game).
        const deleteBtn = i === 0 ? '<button type="button" class="ghost-btn danger-btn pod-delete-last-btn">Delete this game</button>' : "";
        return `
          <div class="pod-game-row">
            <div class="session-meta">${when}${g.notes ? " — " + g.notes : ""}</div>
            <div class="pod-game-participants">${participantsHTML}</div>
            ${deleteBtn}
          </div>
        `;
      })
      .join("");
    const deleteBtn = list.querySelector(".pod-delete-last-btn");
    if (deleteBtn) deleteBtn.addEventListener("click", deleteLastGame);
  }

  async function deleteLastGame() {
    const confirmed = window.confirm("Delete the most recently logged game and revert its rating changes?");
    if (!confirmed) return;
    try {
      await api("DELETE", "/api/pod/games/last");
      await refreshPodData();
    } catch (e) {
      window.alert(e.message);
    }
  }

  // ---- entry point ----

  async function refreshPodData() {
    try {
      const [decksData, playersData, gamesData] = await Promise.all([
        api("GET", "/api/pod/decks"),
        api("GET", "/api/pod/players"),
        api("GET", "/api/pod/games"),
      ]);
      activeDecks = decksData.decks.filter((d) => !d.archived);
      refreshAllDeckSelects();
      renderDecksList(decksData.decks);
      renderPlayersList(playersData.players);
      renderGamesList(gamesData.games);
    } catch (e) {
      window.alert(e.message);
    }
  }

  async function showPodTracker() {
    showScreen("screen-pod");
    await refreshPodData();
  }

  $("pod-add-participant-btn").addEventListener("click", addParticipantRow);
  $("pod-log-game-btn").addEventListener("click", submitLogGame);
  $("pod-register-deck-btn").addEventListener("click", submitRegisterDeck);
  const commanderInput = $("pod-deck-commander-input");
  commanderInput.addEventListener("input", () => {
    clearTimeout(deckSearchDebounceTimer);
    deckSearchDebounceTimer = setTimeout(searchDeckCommander, 250);
  });

  resetParticipantRows();

  window.CP.showPodTracker = showPodTracker;
})();
