(function () {
  "use strict";

  const MANA_ORDER = ["W", "U", "B", "R", "G", "C"];
  // Must match pool.DEFAULT_MIN_POOL_SIZE server-side -- the live preview
  // needs to gate "Start dueling" on the SAME threshold the actual
  // session-creation call enforces, or a filter that shows e.g. "2
  // candidates" with an enabled button fails confusingly on click.
  const MIN_POOL_SIZE = 4;
  const $ = (id) => document.getElementById(id);

  // ---- filter state ----
  const activeColors = new Set();
  const activeThemes = new Set();
  let maxDecks = 10000;

  // ---- session state ----
  let sessionId = null;
  let currentPairing = null; // { round, target_rounds, candidates: [a, b] }

  function currentFiltersBody(overrides) {
    return Object.assign(
      {
        colors: activeColors.size ? [...activeColors].join("") : null,
        color_mode: "subset",
        max_decks: maxDecks,
        min_decks: null,
        themes: [...activeThemes],
        themes_mode: "any",
        pool_size: 40,
        min_pool_size: 4,
      },
      overrides || {}
    );
  }

  async function api(method, path, body) {
    const resp = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const err = new Error(data.detail || `${method} ${path} failed (${resp.status})`);
      err.status = resp.status;
      throw err;
    }
    return data;
  }

  function renderColorChips() {
    const wrap = $("color-chips");
    wrap.innerHTML = "";
    MANA_ORDER.forEach((col) => {
      const b = document.createElement("button");
      b.className = "chip";
      b.type = "button";
      b.textContent = col === "C" ? "Colorless" : col;
      b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", () => {
        if (activeColors.has(col)) activeColors.delete(col);
        else activeColors.add(col);
        b.setAttribute("aria-pressed", String(activeColors.has(col)));
        refreshPoolPreview();
      });
      wrap.appendChild(b);
    });
  }

  async function renderThemeChips() {
    const wrap = $("theme-chips");
    try {
      const { slugs } = await api("GET", "/api/themes");
      wrap.innerHTML = "";
      slugs.forEach((theme) => {
        const b = document.createElement("button");
        b.className = "chip";
        b.type = "button";
        b.textContent = theme;
        b.setAttribute("aria-pressed", "false");
        b.addEventListener("click", () => {
          if (activeThemes.has(theme)) activeThemes.delete(theme);
          else activeThemes.add(theme);
          b.setAttribute("aria-pressed", String(activeThemes.has(theme)));
          refreshPoolPreview();
        });
        wrap.appendChild(b);
      });
    } catch (e) {
      wrap.innerHTML = '<span class="spinner-note">couldn\'t load themes</span>';
    }
  }

  async function refreshPoolPreview() {
    const errEl = $("filter-error");
    errEl.classList.add("hidden");
    try {
      // min_pool_size: 1 here so the server always returns a raw count
      // instead of 422ing early -- MIN_POOL_SIZE (matching the real
      // session-creation default) is what actually gates the button, so
      // the preview and the real "Start" click agree on the threshold.
      const { candidates } = await api("POST", "/api/pool", currentFiltersBody({ min_pool_size: 1 }));
      $("pool-count").textContent = candidates.length;
      $("round-estimate").textContent = candidates.length > 1 ? targetRoundEstimate(candidates.length) : "–";

      if (candidates.length < MIN_POOL_SIZE) {
        errEl.textContent = `Need at least ${MIN_POOL_SIZE} matching commanders to duel (${candidates.length} right now) — loosen a filter.`;
        errEl.classList.remove("hidden");
        $("start-btn").disabled = true;
      } else {
        $("start-btn").disabled = false;
      }
    } catch (e) {
      if (e.status === 503) {
        errEl.textContent = "No commander data yet — run `commander-picker update-data` first.";
      } else {
        errEl.textContent = e.message;
      }
      errEl.classList.remove("hidden");
      $("pool-count").textContent = "0";
      $("round-estimate").textContent = "–";
      $("start-btn").disabled = true;
    }
  }

  function targetRoundEstimate(n) {
    // Mirrors elo.py's target_round_count -- purely for the live filter
    // preview; the server computes the authoritative value on session start.
    if (n <= 1) return 0;
    return Math.max(1, Math.round(n * Math.log2(n)));
  }

  function pipsHTML(colors) {
    const list = !colors ? ["C"] : colors.split("");
    return list.map((c) => `<span class="pip ${c.toLowerCase()}">${c}</span>`).join("");
  }

  function cardInnerHTML(c) {
    const tags = c.themes && c.themes.length
      ? `<div class="theme-tags">${c.themes.map((t) => `<span class="tag">${t}</span>`).join("")}</div>`
      : "";
    return `
      <div class="card-top">
        <div class="card-name">${c.name}</div>
        <div class="pips">${pipsHTML(c.color_identity)}</div>
      </div>
      <div class="card-stats"><span>Decks <b>${c.num_decks.toLocaleString()}</b></span></div>
      ${tags}
    `;
  }

  function showScreen(id) {
    ["screen-intro", "screen-duel", "screen-results"].forEach((s) => {
      $(s).classList.toggle("hidden", s !== id);
    });
    $("phase-label").textContent =
      id === "screen-intro" ? "Filter" : id === "screen-duel" ? "Dueling" : "Results";
  }

  function renderPairing(pairing) {
    currentPairing = pairing;
    $("round-num").textContent = pairing.round;
    $("round-target").textContent = pairing.target_rounds;
    $("progress-fill").style.width = Math.min(100, ((pairing.round - 1) / Math.max(1, pairing.target_rounds)) * 100) + "%";

    const cardA = $("card-a"), cardB = $("card-b");
    [cardA, cardB].forEach((el) => {
      el.classList.remove("winner", "loser");
      el.disabled = false;
    });
    cardA.innerHTML = cardInnerHTML(pairing.candidates[0]);
    cardB.innerHTML = cardInnerHTML(pairing.candidates[1]);
  }

  async function startSession() {
    $("start-btn").disabled = true;
    try {
      const data = await api("POST", "/api/sessions", currentFiltersBody());
      sessionId = data.session_id;
      $("pool-label").textContent = `${data.info.pool_size} candidates`;
      showScreen("screen-duel");
      renderPairing(data.pairing);
    } catch (e) {
      $("filter-error").textContent = e.message;
      $("filter-error").classList.remove("hidden");
    } finally {
      $("start-btn").disabled = false;
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
        if (pairing) renderPairing(pairing);
      }, delay);
    } catch (e) {
      window.alert(e.message);
      $("card-a").disabled = false;
      $("card-b").disabled = false;
    }
  }

  async function finishSession() {
    try {
      const { rankings } = await api("POST", `/api/sessions/${sessionId}/finish`);
      renderResults(rankings);
    } catch (e) {
      window.alert(e.message);
    }
  }

  function renderResults(rankings) {
    const list = $("rank-list");
    list.innerHTML = rankings
      .map((c, i) => {
        const delta = c.rating - 1000;
        const deltaClass = delta > 0 ? "up" : "";
        const sign = delta > 0 ? "+" : "";
        return `
          <div class="rank-row ${i === 0 ? "top1" : ""}">
            <div class="rank-num">${i + 1}</div>
            <div class="rank-name-line">
              <div class="pips">${pipsHTML(c.color_identity)}</div>
              <div class="rank-name">${c.name}</div>
            </div>
            <div class="rank-rating ${deltaClass}">${Math.round(c.rating)} <span style="opacity:.6">(${sign}${Math.round(delta)})</span></div>
          </div>
        `;
      })
      .join("");
    showScreen("screen-results");
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
  $("again-btn").addEventListener("click", () => {
    sessionId = null;
    currentPairing = null;
    showScreen("screen-intro");
    refreshPoolPreview();
  });
  $("start-btn").addEventListener("click", startSession);
  $("max-decks").addEventListener("input", (e) => {
    maxDecks = Number(e.target.value);
    $("max-decks-out").textContent = maxDecks.toLocaleString();
  });
  $("max-decks").addEventListener("change", refreshPoolPreview);

  renderColorChips();
  renderThemeChips();
  $("max-decks-out").textContent = maxDecks.toLocaleString();
  refreshPoolPreview();
  showScreen("screen-intro");
})();
