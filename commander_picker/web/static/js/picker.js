// Filter screen, duel screen, and results screen -- the largest single
// module, ported near-verbatim from the old monolithic app.js. Exposes
// CP.showFilterScreen (the home screen's "Pick a commander" card calls
// this) and CP.resumeSession (sessions-list.js's row click calls this
// cross-module, since resuming mutates this module's own private
// session state and re-enters its own duel/results rendering).
(function () {
  "use strict";

  const { $, api, pipsHTML, manaCostHTML, BRACKET_LABELS, renderColorChips, wireColorModeToggle, showScreen, renderRankList } =
    window.CP;

  // Must match pool.DEFAULT_MIN_POOL_SIZE server-side -- the live preview
  // needs to gate "Start dueling" on the SAME threshold the actual
  // session-creation call enforces, or a filter that shows e.g. "2
  // candidates" with an enabled button fails confusingly on click.
  const MIN_POOL_SIZE = 4;

  // ---- filter state ----
  const activeColors = new Set();
  const activeThemes = new Set(); // archetype UI is hidden (see index.html) -- stays empty
  let colorMode = "subset"; // "subset" (any combo within --colors) or "exact"
  let maxDecks = 10000;
  let minDecks = 100;
  let poolSize = 40;

  // ---- session state ----
  let sessionId = null;
  let sessionMode = "duel"; // the active session's mode, set once it's created (see startSession)
  let currentPairing = null; // { round, target_rounds, candidates: [a, b], round_label? }

  // ---- filter-screen mode selection, before a session exists ----
  let selectedMode = "duel"; // "duel" or "bracket" -- which engine "Start" will create
  const BRACKET_SIZES = [4, 8, 16, 32, 64];
  let bracketPoolSize = null; // chosen preset from BRACKET_SIZES, or null until picked

  // ---- custom-list mode: hand-picked commanders instead of a filtered
  // pool (see searchCommanders/renderCustomList). Independent of
  // selectedMode -- a custom list can still be duel or bracket. ----
  let poolSource = "filtered"; // "filtered" or "custom"
  const customList = []; // [{name, color_identity, num_decks}, ...], insertion order preserved
  let searchDebounceTimer = null;

  function currentFiltersBody(overrides) {
    return Object.assign(
      {
        colors: activeColors.size ? [...activeColors].join("") : null,
        color_mode: colorMode,
        max_decks: maxDecks,
        min_decks: minDecks,
        themes: [...activeThemes],
        themes_mode: "any",
        pool_size: poolSize,
        min_pool_size: 4,
        mode: "duel",
      },
      overrides || {}
    );
  }

  async function refreshPoolPreview() {
    const errEl = $("filter-error");
    errEl.classList.add("hidden");
    try {
      // min_pool_size: 1 here so the server always returns a raw count
      // instead of 422ing early -- MIN_POOL_SIZE (matching the real
      // session-creation default) is what actually gates the button, so
      // the preview and the real "Start" click agree on the threshold.
      const { total_matches } = await api(
        "POST",
        "/api/pool",
        currentFiltersBody({ min_pool_size: 1, mode: selectedMode })
      );
      $("total-matches").textContent = total_matches.toLocaleString();

      if (selectedMode === "bracket") {
        updateBracketSizeChipAvailability(total_matches);
        if (!bracketPoolSize) {
          $("pool-count-line2").textContent = "Pick a bracket size below.";
          $("start-btn").disabled = true;
        } else if (total_matches < bracketPoolSize) {
          $("pool-count-line2").innerHTML = `Bracket of <b>${bracketPoolSize}</b>`;
          errEl.textContent =
            `Only ${total_matches} commander(s) match these filters -- not enough for a bracket of ` +
            `${bracketPoolSize}. Loosen a filter or pick a smaller size.`;
          errEl.classList.remove("hidden");
          $("start-btn").disabled = true;
        } else {
          const rounds = Math.log2(bracketPoolSize);
          $("pool-count-line2").innerHTML =
            `Bracket of <b>${bracketPoolSize}</b>, <b>${rounds}</b> round${rounds === 1 ? "" : "s"} to a champion`;
          $("start-btn").disabled = false;
        }
      } else {
        const duelPoolSize = Math.min(total_matches, poolSize);
        const rounds = duelPoolSize > 1 ? targetRoundEstimate(duelPoolSize) : "–";
        $("pool-count-line2").innerHTML = `Dueling with up to <b>${poolSize}</b>, <b>${rounds}</b> rounds`;
        if (total_matches < MIN_POOL_SIZE) {
          errEl.textContent = `Need at least ${MIN_POOL_SIZE} matching commanders to duel (${total_matches} right now) — loosen a filter.`;
          errEl.classList.remove("hidden");
          $("start-btn").disabled = true;
        } else {
          $("start-btn").disabled = false;
        }
      }
    } catch (e) {
      if (e.status === 503) {
        errEl.textContent = "No commander data yet — run `commander-picker update-data` first.";
      } else {
        errEl.textContent = e.message;
      }
      errEl.classList.remove("hidden");
      $("total-matches").textContent = "0";
      $("pool-count-line2").textContent = "";
      $("start-btn").disabled = true;
    }
  }

  function renderBracketSizeChips() {
    const wrap = $("bracket-size-chips");
    wrap.innerHTML = "";
    BRACKET_SIZES.forEach((size) => {
      const b = document.createElement("button");
      b.className = "chip";
      b.type = "button";
      b.textContent = String(size);
      b.setAttribute("aria-pressed", String(bracketPoolSize === size));
      b.addEventListener("click", () => {
        if (b.disabled) return;
        bracketPoolSize = size;
        wrap.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c === b)));
        refreshPoolPreview();
      });
      wrap.appendChild(b);
    });
  }

  // Presets larger than what the current filters actually match are
  // disabled rather than left clickable-but-doomed -- a filter that
  // only matches 10 commanders can't have "32" selected in the first
  // place, so there's never a "not enough candidates" surprise after
  // the fact.
  function updateBracketSizeChipAvailability(totalMatches) {
    $("bracket-size-chips")
      .querySelectorAll(".chip")
      .forEach((btn) => {
        const size = Number(btn.textContent);
        const disabled = size > totalMatches;
        btn.disabled = disabled;
        btn.classList.toggle("chip-disabled", disabled);
        if (disabled && bracketPoolSize === size) {
          bracketPoolSize = null;
          btn.setAttribute("aria-pressed", "false");
        }
      });
  }

  function setFilterMode(mode) {
    selectedMode = mode;
    $("pool-size-label-row").textContent = mode === "bracket" ? "Bracket size" : "Duel pool size";
    $("pool-size-row").classList.toggle("hidden", mode === "bracket");
    $("bracket-size-chips").classList.toggle("hidden", mode !== "bracket");
    $("start-btn").textContent = mode === "bracket" ? "Start bracket" : "Start dueling";
    if (mode === "bracket") renderBracketSizeChips();
    if (poolSource === "custom") renderCustomList();
    else refreshPoolPreview();
  }

  function setPoolSource(source) {
    poolSource = source;
    $("filter-controls").classList.toggle("hidden", source === "custom");
    $("custom-list-controls").classList.toggle("hidden", source !== "custom");
    if (source === "custom") {
      renderCustomList();
    } else {
      // renderCustomList() overwrites #pool-count-line1's markup (including
      // the #total-matches element refreshPoolPreview depends on) -- restore
      // it before handing back to the filtered-mode preview.
      $("pool-count-line1").innerHTML = '<b id="total-matches">–</b> commanders match your filters';
      refreshPoolPreview();
    }
  }

  async function searchCommanders() {
    const q = $("commander-search-input").value.trim();
    const resultsEl = $("commander-search-results");
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
      const alreadyAdded = new Set(customList.map((c) => c.name));
      resultsEl.innerHTML = results
        .map(
          (r) => `
            <button type="button" class="autocomplete-item" data-name="${r.name}" ${alreadyAdded.has(r.name) ? "disabled" : ""}>
              ${pipsHTML(r.color_identity)}
              <span>${r.name}${alreadyAdded.has(r.name) ? " (added)" : ""}</span>
              <span class="autocomplete-item-decks">${r.num_decks.toLocaleString()} decks</span>
            </button>
          `
        )
        .join("");
      resultsEl.querySelectorAll(".autocomplete-item").forEach((btn) => {
        btn.addEventListener("click", () => {
          if (btn.disabled) return;
          const r = results.find((x) => x.name === btn.dataset.name);
          customList.push(r);
          $("commander-search-input").value = "";
          resultsEl.classList.add("hidden");
          resultsEl.innerHTML = "";
          renderCustomList();
        });
      });
      resultsEl.classList.remove("hidden");
    } catch (e) {
      resultsEl.innerHTML = `<div class="spinner-note" style="padding: 9px 12px;">${e.message}</div>`;
      resultsEl.classList.remove("hidden");
    }
  }

  function renderCustomList() {
    $("custom-list-count").textContent = customList.length;
    const itemsEl = $("custom-list-items");
    if (!customList.length) {
      itemsEl.innerHTML = '<div class="spinner-note">Search above and add commanders to build your list.</div>';
    } else {
      itemsEl.innerHTML = customList
        .map(
          (c, i) => `
            <div class="custom-list-row" data-index="${i}">
              <div class="custom-list-name">${pipsHTML(c.color_identity)}${c.name}</div>
              <button type="button" class="ghost-btn custom-list-remove">✕ Remove</button>
            </div>
          `
        )
        .join("");
      itemsEl.querySelectorAll(".custom-list-row").forEach((row) => {
        row.querySelector(".custom-list-remove").addEventListener("click", () => {
          customList.splice(Number(row.dataset.index), 1);
          renderCustomList();
        });
      });
    }

    const errEl = $("filter-error");
    errEl.classList.add("hidden");
    $("pool-count-line1").innerHTML = `<b>${customList.length}</b> commander(s) in your list`;

    if (selectedMode === "bracket") {
      if (BRACKET_SIZES.includes(customList.length)) {
        const rounds = Math.log2(customList.length);
        $("pool-count-line2").innerHTML =
          `Bracket of <b>${customList.length}</b>, <b>${rounds}</b> round${rounds === 1 ? "" : "s"} to a champion`;
        $("start-btn").disabled = false;
      } else {
        $("pool-count-line2").textContent = "";
        errEl.textContent =
          `Bracket mode needs a power-of-two list size (4, 8, 16, 32, or 64) -- currently ${customList.length}.`;
        errEl.classList.remove("hidden");
        $("start-btn").disabled = true;
      }
    } else {
      $("pool-count-line2").innerHTML = `Dueling with your <b>${customList.length}</b>-commander list`;
      if (customList.length < 2) {
        errEl.textContent = `Add at least 2 commanders to duel (${customList.length} so far).`;
        errEl.classList.remove("hidden");
        $("start-btn").disabled = true;
      } else {
        $("start-btn").disabled = false;
      }
    }
  }

  function targetRoundEstimate(n) {
    // Mirrors elo.py's target_round_count -- purely for the live filter
    // preview; the server computes the authoritative value on session start.
    if (n <= 1) return 0;
    return Math.max(1, Math.round(n * Math.log2(n)));
  }

  // Target width for a single card face -- each image renders at (up
  // to) this size regardless of how many faces this commander has or
  // how much extra room the duel layout happens to give its button,
  // so a plain 1-image commander doesn't balloon to fill the whole
  // card-btn while a 2-image commander's faces stay small by
  // comparison. A 2-image group is capped at roughly double this
  // (plus the seam gap) so each of its faces still lands at close to
  // the same size as a single-image opponent's.
  const CARD_ART_TARGET_WIDTH = 210;
  const CARD_ART_GAP = 1;

  function cardInnerHTML(c) {
    const tags = c.themes && c.themes.length
      ? `<div class="theme-tags">${c.themes.map((t) => `<span class="tag">${t}</span>`).join("")}</div>`
      : "";
    // image_urls is only populated when `update-data` fetched Scryfall
    // art (see scryfall_client.py) -- gracefully omit the banner
    // entirely rather than showing a broken-image icon when absent.
    // Two entries means a Partner/Background pair (two separate cards)
    // or a double-faced/transform commander (front + back) -- shown
    // side by side.
    const count = c.image_urls ? c.image_urls.length : 0;
    const maxWidth = count * CARD_ART_TARGET_WIDTH + Math.max(0, count - 1) * CARD_ART_GAP;
    const art = count
      ? `<div class="card-art-group" style="max-width:${maxWidth}px">${c.image_urls
          .map((url) => `<img class="card-art" src="${url}" alt="" loading="lazy" onerror="this.remove()" />`)
          .join("")}</div>`
      : "";
    // rank/mana_cost/type_line/power_level are only populated when
    // `update-data`/`enrich-commanders` captured them (EDHREC rank;
    // mana cost/type line from Scryfall; power_level from a cached
    // per-commander detail page) -- gracefully omit each when absent,
    // same posture as image_urls above.
    const rankBadge = c.rank ? `<span class="tag rank-tag">#${c.rank} on this page</span>` : "";
    const powerBadge = c.power_level
      ? `<span class="tag power-tag">Bracket ${c.power_level} · ${BRACKET_LABELS[c.power_level]}</span>`
      : "";
    const manaCost = c.mana_cost ? `<div class="mana-cost">${manaCostHTML(c.mana_cost)}</div>` : "";
    const typeLine = !c.mana_cost && c.type_line ? `<div class="type-line">${c.type_line}</div>` : "";
    return `
      ${art}
      <div class="card-top">
        <div class="card-name">${c.name}</div>
        <div class="pips">${pipsHTML(c.color_identity)}</div>
      </div>
      ${manaCost}
      ${typeLine}
      <div class="card-stats"><span>Decks <b>${c.num_decks.toLocaleString()}</b></span></div>
      ${tags}
      ${rankBadge}
      ${powerBadge}
    `;
  }

  function renderPairing(pairing) {
    currentPairing = pairing;
    $("round-meta-text").innerHTML =
      sessionMode === "bracket"
        ? pairing.round_label
        : `Round <b>${pairing.round}</b> of <b>${pairing.target_rounds}</b>`;
    $("progress-fill").style.width = Math.min(100, ((pairing.round - 1) / Math.max(1, pairing.target_rounds)) * 100) + "%";
    // Nothing to undo until at least one pick has been made -- pairing.round
    // is always rounds_completed + 1, so round 1 means a clean slate,
    // whether that's a fresh session or one just undone back to the start.
    if (sessionMode !== "bracket") $("undo-btn").disabled = pairing.round <= 1;

    const cardA = $("card-a"), cardB = $("card-b");
    [cardA, cardB].forEach((el) => {
      el.classList.remove("winner", "loser");
      el.disabled = false;
    });
    const [candA, candB] = pairing.candidates;
    cardA.innerHTML = cardInnerHTML(candA);
    cardB.innerHTML = cardInnerHTML(candB);
  }

  // Shared by startSession and resumeSession -- both end up with a
  // session id/mode and a pairing to show, just from different sources
  // (a fresh POST /api/sessions vs. an existing session's current state).
  function enterDuelScreen(info, pairing) {
    sessionMode = info.mode;
    $("pool-label").textContent = `${info.pool_size} candidates`;
    $("finish-btn").classList.toggle("hidden", sessionMode === "bracket");
    $("undo-btn").classList.toggle("hidden", sessionMode === "bracket");
    $("bracket-tree-live").classList.toggle("hidden", sessionMode !== "bracket");
    showScreen("screen-duel");
    renderPairing(pairing); // also sets undo-btn.disabled correctly (round 1 vs. resumed mid-session)
    if (sessionMode === "bracket") refreshLiveBracketTree();
  }

  async function startSession() {
    $("start-btn").disabled = true;
    try {
      let data;
      if (poolSource === "custom") {
        data = await api("POST", "/api/sessions/custom", {
          names: customList.map((c) => c.name),
          mode: selectedMode,
        });
      } else {
        const body =
          selectedMode === "bracket"
            ? currentFiltersBody({ mode: "bracket", pool_size: bracketPoolSize })
            : currentFiltersBody({ mode: "duel" });
        data = await api("POST", "/api/sessions", body);
      }
      sessionId = data.session_id;
      enterDuelScreen(data.info, data.pairing);
    } catch (e) {
      $("filter-error").textContent = e.message;
      $("filter-error").classList.remove("hidden");
    } finally {
      $("start-btn").disabled = false;
    }
  }

  async function resumeSession(id) {
    try {
      const info = await api("GET", `/api/sessions/${id}`);
      sessionId = id;
      if (info.status === "active") {
        const pairing = await api("GET", `/api/sessions/${id}/pairing`);
        if (pairing) {
          enterDuelScreen(info, pairing);
          return;
        }
        // Shouldn't normally happen (an active session always has a next
        // pairing, or auto-finishes) -- fall through to results rather
        // than leaving the screen stuck if it somehow does.
      }
      sessionMode = info.mode;
      await showFinalResults();
    } catch (e) {
      window.alert(e.message);
    }
  }

  async function undoLastPick() {
    $("undo-btn").disabled = true;
    try {
      const pairing = await api("POST", `/api/sessions/${sessionId}/undo`);
      if (pairing) {
        renderPairing(pairing);
      } else {
        // Shouldn't normally happen -- undoing always leaves an active
        // session with a next pairing -- but handle it rather than leaving
        // the screen stuck if it somehow does.
        showFinalResults();
      }
    } catch (e) {
      window.alert(e.message);
      $("undo-btn").disabled = false;
    }
  }

  async function refreshLiveBracketTree() {
    try {
      const bracket = await api("GET", `/api/sessions/${sessionId}/bracket`);
      renderBracketTree("bracket-tree-live", bracket, { compact: true });
    } catch (e) {
      // Non-critical -- the duel itself still works even if the tree
      // strip fails to load, so fail silently rather than alert().
    }
  }

  async function pick(winnerName, loserName, winnerEl, loserEl) {
    $("card-a").disabled = true;
    $("card-b").disabled = true;
    winnerEl.classList.add("winner");
    loserEl.classList.add("loser");

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const delay = reduceMotion ? 0 : 420;

    try {
      const pairing = await api("POST", `/api/sessions/${sessionId}/pick`, { winner: winnerName, loser: loserName });
      setTimeout(() => {
        if (pairing) {
          renderPairing(pairing);
          if (sessionMode === "bracket") refreshLiveBracketTree();
        } else {
          // The session auto-finished (reached its round count, or the
          // bracket's final was just decided) -- there's no next
          // pairing, so show final results instead of leaving the last
          // duel frozen on screen with nothing to do.
          showFinalResults();
        }
      }, delay);
    } catch (e) {
      window.alert(e.message);
      $("card-a").disabled = false;
      $("card-b").disabled = false;
    }
  }

  async function showFinalResults() {
    try {
      if (sessionMode === "bracket") {
        const bracket = await api("GET", `/api/sessions/${sessionId}/bracket`);
        renderBracketResults(bracket);
      } else {
        const { rankings, winner_challenge_slug } = await api("GET", `/api/sessions/${sessionId}/results`);
        renderResults(rankings, winner_challenge_slug);
      }
    } catch (e) {
      window.alert(e.message);
    }
  }

  async function finishSession() {
    try {
      const { rankings, winner_challenge_slug } = await api("POST", `/api/sessions/${sessionId}/finish`);
      renderResults(rankings, winner_challenge_slug);
    } catch (e) {
      window.alert(e.message);
    }
  }

  function renderResults(rankings, winnerChallengeSlug) {
    $("champion-banner").classList.add("hidden");
    $("bracket-tree-final").classList.add("hidden");
    $("rank-list").classList.remove("hidden");
    $("results-lede").textContent =
      "Final standings for this run — every pick also feeds the all-time leaderboard below. Tap a commander to see its card(s) full size.";
    renderRankList("rank-list", rankings, (c) => {
      const delta = c.rating - 1000;
      const sign = delta > 0 ? "+" : "";
      return {
        cls: delta > 0 ? "up" : "",
        html: `${Math.round(c.rating)} <span style="opacity:.6">(${sign}${Math.round(delta)})</span>`,
      };
    });
    showScreen("screen-results");
    window.CP.maybeShowChallengeNudge(winnerChallengeSlug, rankings.length ? rankings[0].name : null);
  }

  function renderBracketResults(bracket) {
    $("rank-list").classList.add("hidden");
    $("results-lede").textContent =
      "The bracket's played out — every match also fed the all-time leaderboard below.";
    $("champion-banner").classList.remove("hidden");
    $("champion-banner").innerHTML = bracket.champion
      ? `<div class="champion-label">🏆 Champion</div><div class="champion-name">${bracket.champion}</div>`
      : "";
    $("bracket-tree-final").classList.remove("hidden");
    renderBracketTree("bracket-tree-final", bracket, { compact: false });
    showScreen("screen-results");
    window.CP.maybeShowChallengeNudge(bracket.winner_challenge_slug, bracket.champion);
  }

  // Mirrors elo.bracket_round_label -- purely for display, the server's
  // own round_label (used live, in renderPairing) is authoritative.
  function bracketRoundLabel(roundNum, totalRounds) {
    const remaining = totalRounds - roundNum;
    if (remaining === 0) return "Final";
    if (remaining === 1) return "Semifinal";
    if (remaining === 2) return "Quarterfinal";
    return `Round of ${2 ** (remaining + 1)}`;
  }

  function renderBracketTree(containerId, bracket, opts) {
    const compact = !!(opts && opts.compact);
    const wrap = $(containerId);
    const totalRounds = bracket.rounds.length;
    wrap.classList.toggle("bracket-tree-compact", compact);
    wrap.innerHTML = bracket.rounds
      .map((matches, i) => {
        const label = bracketRoundLabel(i + 1, totalRounds);
        const matchesHTML = matches
          .map((m) => {
            const a = m.seed_a || "TBD";
            const b = m.seed_b || "TBD";
            const aCls = !m.winner ? "" : m.winner === m.seed_a ? "bracket-winner" : "bracket-loser";
            const bCls = !m.winner ? "" : m.winner === m.seed_b ? "bracket-winner" : "bracket-loser";
            return `
              <div class="bracket-match">
                <div class="bracket-slot ${aCls}">${a}</div>
                <div class="bracket-slot ${bCls}">${b}</div>
              </div>
            `;
          })
          .join("");
        return `<div class="bracket-round"><div class="bracket-round-label">${label}</div>${matchesHTML}</div>`;
      })
      .join("");
  }

  $("card-a").addEventListener("click", () => {
    if (!currentPairing) return;
    pick(currentPairing.candidates[0].name, currentPairing.candidates[1].name, $("card-a"), $("card-b"));
  });
  $("card-b").addEventListener("click", () => {
    if (!currentPairing) return;
    pick(currentPairing.candidates[1].name, currentPairing.candidates[0].name, $("card-b"), $("card-a"));
  });
  $("finish-btn").addEventListener("click", finishSession);
  $("undo-btn").addEventListener("click", undoLastPick);
  document.addEventListener("keydown", (e) => {
    // 1/2 or the arrow keys pick a duel card, mirroring the CLI's 1/2
    // input -- only while the duel screen is actually showing, a
    // pairing is loaded, and the cards aren't already mid-pick-animation
    // locked (renderPairing re-enables them; pick() disables them).
    if ($("screen-duel").classList.contains("hidden") || !currentPairing) return;
    const cardA = $("card-a"), cardB = $("card-b");
    if (cardA.disabled || cardB.disabled) return;
    if (e.key === "1" || e.key === "ArrowLeft") {
      pick(currentPairing.candidates[0].name, currentPairing.candidates[1].name, cardA, cardB);
    } else if (e.key === "2" || e.key === "ArrowRight") {
      pick(currentPairing.candidates[1].name, currentPairing.candidates[0].name, cardB, cardA);
    } else if (e.key === "u" && !$("undo-btn").disabled) {
      undoLastPick();
    }
  });
  // "Duel again" is an unambiguous continuation of the current flow, so
  // it goes straight back to the filter screen -- unlike the general
  // "back/exit buttons go home" rule applied to the other screens.
  $("again-btn").addEventListener("click", () => {
    sessionId = null;
    currentPairing = null;
    showScreen("screen-intro");
    refreshPoolPreview();
  });
  $("start-btn").addEventListener("click", startSession);
  $("filter-home-btn").addEventListener("click", () => showScreen("screen-home"));
  $("filter-reset-btn").addEventListener("click", () => {
    activeColors.clear();
    colorMode = "subset";
    maxDecks = 10000;
    minDecks = 100;
    poolSize = 40;
    customList.length = 0;
    $("commander-search-input").value = "";
    $("commander-search-results").classList.add("hidden");
    $("commander-search-results").innerHTML = "";

    renderColorChips("color-chips", activeColors, refreshPoolPreview);
    document.querySelectorAll("#color-mode-toggle .segmented-btn").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.mode === "subset"));
    });
    $("max-decks-slider").value = maxDecks;
    $("max-decks-input").value = maxDecks;
    $("min-decks-slider").value = minDecks;
    $("min-decks-input").value = minDecks;
    $("pool-size-input").value = poolSize;

    // setFilterMode("duel") handles the pool-size-row/bracket-size-chips
    // visibility toggle, the start-btn label, and rebuilding the bracket
    // chips fresh (which resets bracketPoolSize to null as a side effect) --
    // same reason wireColorModeToggle's own click handler doesn't reset
    // aria-pressed on its own, just wires clicks.
    setFilterMode("duel");
    document.querySelectorAll("#mode-toggle .segmented-btn").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.mode === "duel"));
    });
    document.querySelectorAll("#pool-source-toggle .segmented-btn").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.source === "filtered"));
    });
    setPoolSource("filtered");

    refreshPoolPreview();
  });

  const decksSlider = $("max-decks-slider");
  const decksInput = $("max-decks-input");
  decksSlider.addEventListener("input", () => {
    maxDecks = Number(decksSlider.value);
    decksInput.value = maxDecks;
  });
  decksSlider.addEventListener("change", refreshPoolPreview);
  decksInput.addEventListener("change", () => {
    const value = Math.max(1, Math.floor(Number(decksInput.value) || 0));
    maxDecks = value;
    decksInput.value = value;
    // Keep the slider in sync when the typed value is in its range;
    // clamp visually rather than fighting the slider's own min/max.
    decksSlider.value = Math.min(Math.max(value, Number(decksSlider.min)), Number(decksSlider.max));
    refreshPoolPreview();
  });

  const minDecksSlider = $("min-decks-slider");
  const minDecksInput = $("min-decks-input");
  minDecksSlider.addEventListener("input", () => {
    minDecks = Number(minDecksSlider.value);
    minDecksInput.value = minDecks;
  });
  minDecksSlider.addEventListener("change", refreshPoolPreview);
  minDecksInput.addEventListener("change", () => {
    const value = Math.max(0, Math.floor(Number(minDecksInput.value) || 0));
    minDecks = value;
    minDecksInput.value = value;
    minDecksSlider.value = Math.min(Math.max(value, Number(minDecksSlider.min)), Number(minDecksSlider.max));
    refreshPoolPreview();
  });

  const poolSizeInput = $("pool-size-input");
  poolSizeInput.addEventListener("change", () => {
    const value = Math.min(200, Math.max(4, Math.floor(Number(poolSizeInput.value) || 40)));
    poolSize = value;
    poolSizeInput.value = value;
    refreshPoolPreview();
  });

  wireColorModeToggle("color-mode-toggle", (m) => { colorMode = m; }, refreshPoolPreview);
  wireColorModeToggle("mode-toggle", setFilterMode, () => {});

  document.querySelectorAll("#pool-source-toggle .segmented-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#pool-source-toggle .segmented-btn").forEach((b) => {
        b.setAttribute("aria-pressed", String(b === btn));
      });
      setPoolSource(btn.dataset.source);
    });
  });

  const searchInput = $("commander-search-input");
  searchInput.addEventListener("input", () => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(searchCommanders, 250);
  });

  renderColorChips("color-chips", activeColors, refreshPoolPreview);

  Object.assign(window.CP, {
    showFilterScreen: () => {
      showScreen("screen-intro");
      refreshPoolPreview();
    },
    resumeSession,
  });
})();
