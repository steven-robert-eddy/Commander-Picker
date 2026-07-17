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
  const activeThemes = new Set(); // archetype UI is hidden (see index.html) -- stays empty
  let colorMode = "subset"; // "subset" (any combo within --colors) or "exact"
  let maxDecks = 10000;
  let poolSize = 40;

  // ---- session state ----
  let sessionId = null;
  let currentPairing = null; // { round, target_rounds, candidates: [a, b] }

  function currentFiltersBody(overrides) {
    return Object.assign(
      {
        colors: activeColors.size ? [...activeColors].join("") : null,
        color_mode: colorMode,
        max_decks: maxDecks,
        min_decks: null,
        themes: [...activeThemes],
        themes_mode: "any",
        pool_size: poolSize,
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
      const label = col === "C" ? "Colorless" : col;
      // Same Scryfall mana symbol art as the duel/results pips (see
      // MANA_SYMBOL_BASE_URL below), not a plain colored circle.
      b.innerHTML = `<img class="chip-pip" src="${MANA_SYMBOL_BASE_URL}${col}.svg" alt="" />${label}`;
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

  // Currently unused -- archetype filtering is hidden in the UI (see
  // index.html), left defined so it's a one-line change to bring back
  // (`renderThemeChips();` in the init section below) if that changes.
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
    $("pool-size-label").textContent = poolSize;
    try {
      // min_pool_size: 1 here so the server always returns a raw count
      // instead of 422ing early -- MIN_POOL_SIZE (matching the real
      // session-creation default) is what actually gates the button, so
      // the preview and the real "Start" click agree on the threshold.
      const { total_matches, candidates } = await api("POST", "/api/pool", currentFiltersBody({ min_pool_size: 1 }));
      $("total-matches").textContent = total_matches.toLocaleString();
      const duelPoolSize = Math.min(total_matches, poolSize);
      $("round-estimate").textContent = duelPoolSize > 1 ? targetRoundEstimate(duelPoolSize) : "–";

      if (total_matches < MIN_POOL_SIZE) {
        errEl.textContent = `Need at least ${MIN_POOL_SIZE} matching commanders to duel (${total_matches} right now) — loosen a filter.`;
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
      $("total-matches").textContent = "0";
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

  // Scryfall's own mana symbol art -- the real sun/water-drop/skull/
  // fireball/tree glyphs players recognize from the cards themselves,
  // not a plain colored circle with a letter in it.
  const MANA_SYMBOL_BASE_URL = "https://svgs.scryfall.io/card-symbols/";

  function pipsHTML(colors) {
    const list = !colors ? ["C"] : colors.split("");
    return list
      .map((c) => `<img class="pip" src="${MANA_SYMBOL_BASE_URL}${c}.svg" alt="${c}" loading="lazy" />`)
      .join("");
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
    return `
      ${art}
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
    const [candA, candB] = pairing.candidates;
    cardA.innerHTML = cardInnerHTML(candA);
    cardB.innerHTML = cardInnerHTML(candB);
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
        if (pairing) {
          renderPairing(pairing);
        } else {
          // The session auto-finished (reached its round count) --
          // there's no next pairing, so show final results instead of
          // leaving the last duel frozen on screen with nothing to do.
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
      const { rankings } = await api("GET", `/api/sessions/${sessionId}/results`);
      renderResults(rankings);
    } catch (e) {
      window.alert(e.message);
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
        const hasArt = c.image_urls && c.image_urls.length;
        const thumb = hasArt
          ? `<div class="rank-thumb-group">${c.image_urls
              .map((url) => `<img class="rank-thumb" src="${url}" alt="" loading="lazy" onerror="this.remove()" />`)
              .join("")}</div>`
          : "";
        const interactiveAttrs = hasArt ? 'tabindex="0" role="button"' : "";
        return `
          <div class="rank-row ${i === 0 ? "top1" : ""} ${hasArt ? "has-art" : ""}" data-idx="${i}" ${interactiveAttrs}>
            <div class="rank-num">${i + 1}</div>
            <div class="rank-name-line">
              ${thumb}
              <div class="pips">${pipsHTML(c.color_identity)}</div>
              <div class="rank-name">${c.name}</div>
            </div>
            <div class="rank-rating ${deltaClass}">${Math.round(c.rating)} <span style="opacity:.6">(${sign}${Math.round(delta)})</span></div>
          </div>
        `;
      })
      .join("");
    // Click a ranked commander to see its card(s) full size, rather
    // than the compact list thumbnail -- listeners reference `rankings`
    // by closure (data-idx just identifies which row, not the data
    // itself) so there's no HTML-attribute escaping to worry about for
    // image URLs or names.
    list.querySelectorAll(".rank-row.has-art").forEach((row) => {
      const c = rankings[Number(row.dataset.idx)];
      row.addEventListener("click", () => openLightbox(c.image_urls, c.name));
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault(); // stop the page from scrolling on Space
          openLightbox(c.image_urls, c.name);
        }
      });
    });
    showScreen("screen-results");
  }

  function openLightbox(imageUrls, name) {
    if (!imageUrls || !imageUrls.length) return;
    $("lightbox-name").textContent = name || "";
    $("lightbox-images").innerHTML = imageUrls
      .map((url) => `<img src="${url}" alt="${name || ""}" />`)
      .join("");
    $("lightbox").classList.remove("hidden");
  }

  function closeLightbox() {
    $("lightbox").classList.add("hidden");
    $("lightbox-images").innerHTML = "";
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
  $("lightbox-close").addEventListener("click", closeLightbox);
  $("lightbox").addEventListener("click", (e) => {
    if (e.target.id === "lightbox") closeLightbox(); // click on backdrop, not the card image itself
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeLightbox();
  });
  $("again-btn").addEventListener("click", () => {
    sessionId = null;
    currentPairing = null;
    showScreen("screen-intro");
    refreshPoolPreview();
  });
  $("start-btn").addEventListener("click", startSession);

  // Slider and number input both drive maxDecks -- the slider is fast
  // for coarse adjustment, the number input is exact (no more fighting
  // a drag gesture to land on a specific value).
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

  const poolSizeInput = $("pool-size-input");
  poolSizeInput.addEventListener("change", () => {
    const value = Math.min(200, Math.max(4, Math.floor(Number(poolSizeInput.value) || 40)));
    poolSize = value;
    poolSizeInput.value = value;
    refreshPoolPreview();
  });

  document.querySelectorAll("#color-mode-toggle .segmented-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      colorMode = btn.dataset.mode;
      document.querySelectorAll("#color-mode-toggle .segmented-btn").forEach((b) => {
        b.setAttribute("aria-pressed", String(b === btn));
      });
      refreshPoolPreview();
    });
  });

  renderColorChips();
  refreshPoolPreview();
  showScreen("screen-intro");
})();
