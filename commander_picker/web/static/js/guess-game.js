// Guess-the-Commander mini-game: a random commander (>= the minimum
// deck count set below) is picked server-side (see guess_game.py),
// which shows its type line/mana cost up front and reveals one more
// oracle-text line per wrong guess. The server never sends the
// answer, oracle text, or art until the game is won or lost -- see
// guess_game.get_game's `finished` gating.
(function () {
  "use strict";

  const { $, api, pipsHTML, manaCostHTML, showScreen } = window.CP;

  let currentGameId = null;
  let searchDebounceTimer = null;
  let minDecks = 10000;

  function renderFact(info) {
    const manaHTML = info.mana_cost ? `<span class="guess-fact-mana">${manaCostHTML(info.mana_cost)}</span>` : "";
    $("guess-fact-line").innerHTML = `<div class="guess-fact-type">${info.type_line || "Unknown type"}</div>${manaHTML}`;
  }

  function renderTextClues(info) {
    const el = $("guess-text-clues");
    if (!info.text_clues.length) {
      el.innerHTML = '<div class="spinner-note">No rules text revealed yet -- a wrong guess reveals a line.</div>';
      return;
    }
    el.innerHTML = info.text_clues.map((line, i) => `<div class="guess-text-clue-line">${i + 1}. ${line}</div>`).join("");
  }

  function renderHistory(info) {
    $("guess-history").innerHTML = info.guesses
      .map((g, i) => {
        const correct = i === info.guesses.length - 1 && info.status === "won";
        return `<div class="guess-history-row ${correct ? "guess-correct" : "guess-wrong"}">${correct ? "✓" : "✕"} ${g}</div>`;
      })
      .join("");
  }

  function renderReveal(info) {
    $("guess-reveal-panel").classList.remove("hidden");
    $("guess-reveal-name").innerHTML = `<div class="pips">${pipsHTML(info.color_identity)}</div>${info.answer_name}`;
    $("guess-reveal-images").innerHTML = (info.image_urls || [])
      .map((url) => `<img src="${url}" alt="" loading="lazy" onerror="this.remove()" />`)
      .join("");
    $("guess-reveal-text").innerHTML = (info.oracle_text || "")
      .split("\n")
      .filter((l) => l.trim())
      .map((line) => `<div>${line}</div>`)
      .join("");
    $("guess-reveal-meta").textContent = `${(info.num_decks || 0).toLocaleString()} decks on EDHREC`;
    const link = $("guess-reveal-edhrec-link");
    if (info.edhrec_url) {
      link.href = info.edhrec_url;
      link.classList.remove("hidden");
    } else {
      link.classList.add("hidden");
    }
    $("guess-play-again-btn").classList.remove("hidden");
    $("guess-input").disabled = true;
    $("guess-submit-btn").disabled = true;
  }

  function renderGameState(info) {
    renderFact(info);
    renderTextClues(info);
    const n = info.attempts_remaining;
    $("guess-attempts-line").textContent = `${n} guess${n === 1 ? "" : "es"} remaining`;
    renderHistory(info);
    if (info.status !== "in_progress") renderReveal(info);
  }

  function resetScreen() {
    $("guess-error").classList.add("hidden");
    $("guess-error").textContent = "";
    $("guess-history").innerHTML = "";
    $("guess-reveal-panel").classList.add("hidden");
    $("guess-play-again-btn").classList.add("hidden");
    $("guess-input").disabled = false;
    $("guess-input").value = "";
    $("guess-submit-btn").disabled = false;
    $("guess-search-results").classList.add("hidden");
    $("guess-search-results").innerHTML = "";
  }

  async function startNewGame() {
    resetScreen();
    try {
      const info = await api("POST", "/api/guess-game", { min_decks: minDecks });
      currentGameId = info.id;
      renderGameState(info);
    } catch (e) {
      $("guess-error").textContent = e.message;
      $("guess-error").classList.remove("hidden");
    }
  }

  async function submitCurrentGuess() {
    if (!currentGameId || $("guess-input").disabled) return;
    const errEl = $("guess-error");
    errEl.classList.add("hidden");
    const value = $("guess-input").value.trim();
    if (!value) return;
    try {
      const info = await api("POST", `/api/guess-game/${encodeURIComponent(currentGameId)}/guess`, { guess: value });
      $("guess-input").value = "";
      $("guess-search-results").classList.add("hidden");
      $("guess-search-results").innerHTML = "";
      renderGameState(info);
    } catch (e) {
      errEl.textContent = e.message;
      errEl.classList.remove("hidden");
    }
  }

  // Same search-as-you-type pattern as picker.js/pod.js/challenge.js
  // against GET /api/commanders/search -- picking a result just fills
  // the input with the exact name (avoiding typos), it doesn't submit
  // the guess by itself.
  async function searchGuessCommanders() {
    const q = $("guess-input").value.trim();
    const resultsEl = $("guess-search-results");
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
            <button type="button" class="autocomplete-item" data-name="${r.name}">
              ${pipsHTML(r.color_identity)}
              <span>${r.name}</span>
              <span class="autocomplete-item-decks">${r.num_decks.toLocaleString()} decks</span>
            </button>
          `
        )
        .join("");
      resultsEl.querySelectorAll(".autocomplete-item").forEach((btn) => {
        btn.addEventListener("click", () => {
          $("guess-input").value = btn.dataset.name;
          resultsEl.classList.add("hidden");
          resultsEl.innerHTML = "";
          $("guess-input").focus();
        });
      });
      resultsEl.classList.remove("hidden");
    } catch (e) {
      resultsEl.innerHTML = `<div class="spinner-note" style="padding: 9px 12px;">${e.message}</div>`;
      resultsEl.classList.remove("hidden");
    }
  }

  async function showGuessGame() {
    showScreen("screen-guess-game");
    await startNewGame();
  }

  // Same paired slider/number-input sync as the intro screen's own
  // deck-count filters (see picker.js) -- takes effect on the next
  // new game (initial load or Play again), not the game in progress.
  const minDecksSlider = $("guess-min-decks-slider");
  const minDecksInput = $("guess-min-decks-input");
  minDecksSlider.addEventListener("input", () => {
    minDecks = Number(minDecksSlider.value);
    minDecksInput.value = minDecks;
  });
  minDecksInput.addEventListener("change", () => {
    const value = Math.max(0, Math.floor(Number(minDecksInput.value) || 0));
    minDecks = value;
    minDecksInput.value = value;
    minDecksSlider.value = Math.min(Math.max(value, Number(minDecksSlider.min)), Number(minDecksSlider.max));
  });

  const input = $("guess-input");
  input.addEventListener("input", () => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(searchGuessCommanders, 250);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      submitCurrentGuess();
    }
  });
  $("guess-submit-btn").addEventListener("click", submitCurrentGuess);
  $("guess-play-again-btn").addEventListener("click", startNewGame);

  window.CP.showGuessGame = showGuessGame;
})();
