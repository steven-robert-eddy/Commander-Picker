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

  // ---- leaderboard filter state -- deliberately separate from the
  // duel-pool filter state above. Checking "how do my mono-red
  // commanders rank all-time" shouldn't also change what colors your
  // next duel session gets built from. ----
  const leaderboardActiveColors = new Set();
  let leaderboardColorMode = "subset";

  // ---- session state ----
  let sessionId = null;
  let sessionMode = "duel"; // the active session's mode, set once it's created (see startSession)
  let currentPairing = null; // { round, target_rounds, candidates: [a, b], round_label? }

  // ---- filter-screen mode selection, before a session exists ----
  let selectedMode = "duel"; // "duel" or "bracket" -- which engine "Start" will create
  const BRACKET_SIZES = [4, 8, 16, 32, 64];
  let bracketPoolSize = null; // chosen preset from BRACKET_SIZES, or null until picked

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
        mode: "duel",
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

  // Generalized so both the duel-pool filter (#color-chips) and the
  // leaderboard filter (#leaderboard-color-chips) can each drive their
  // own independent Set of active colors without duplicating the chip-
  // building logic.
  function renderColorChips(containerId, activeSet, onChange) {
    const wrap = $(containerId);
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
        if (activeSet.has(col)) activeSet.delete(col);
        else activeSet.add(col);
        b.setAttribute("aria-pressed", String(activeSet.has(col)));
        onChange();
      });
      wrap.appendChild(b);
    });
  }

  // Same generalization for the subset/exact segmented toggle -- one
  // wiring function, two independent instances (duel-pool filter,
  // leaderboard filter).
  function wireColorModeToggle(containerId, setMode, onChange) {
    document.querySelectorAll(`#${containerId} .segmented-btn`).forEach((btn) => {
      btn.addEventListener("click", () => {
        setMode(btn.dataset.mode);
        document.querySelectorAll(`#${containerId} .segmented-btn`).forEach((b) => {
          b.setAttribute("aria-pressed", String(b === btn));
        });
        onChange();
      });
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
    refreshPoolPreview();
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

  // Scryfall's mana-cost shorthand ("{2}{B}{R}") uses the same symbol
  // codes as its symbol-SVG filenames -- reuses MANA_SYMBOL_BASE_URL, no
  // new asset dependency, same trick as pipsHTML above. Hybrid symbols
  // ("{B/R}") use a hyphen in the filename instead of the slash (e.g.
  // "B-R.svg") -- best-effort, matches Scryfall's own convention but
  // unverified live from this sandbox, worth a quick visual check once
  // deployed on a commander with a hybrid-mana cost.
  function manaCostHTML(manaCost) {
    const symbols = manaCost.match(/\{([^}]+)\}/g) || [];
    return symbols
      .map((s) => s.slice(1, -1))
      .map((code) => {
        const filename = code.replace("/", "-");
        return `<img class="pip" src="${MANA_SYMBOL_BASE_URL}${filename}.svg" alt="${code}" loading="lazy" onerror="this.remove()" />`;
      })
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
    // rank/mana_cost/type_line are only populated when `update-data`
    // captured them (EDHREC rank; mana cost/type line from Scryfall) --
    // gracefully omit each when absent, same posture as image_urls above.
    const rankBadge = c.rank ? `<span class="tag rank-tag">#${c.rank} on this page</span>` : "";
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
    `;
  }

  function showScreen(id) {
    ["screen-intro", "screen-duel", "screen-results", "screen-leaderboard"].forEach((s) => {
      $(s).classList.toggle("hidden", s !== id);
    });
    $("phase-label").textContent =
      id === "screen-intro" ? "Filter"
      : id === "screen-duel" ? "Dueling"
      : id === "screen-results" ? "Results"
      : "Leaderboard";
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

  async function startSession() {
    $("start-btn").disabled = true;
    try {
      const body =
        selectedMode === "bracket"
          ? currentFiltersBody({ mode: "bracket", pool_size: bracketPoolSize })
          : currentFiltersBody({ mode: "duel" });
      const data = await api("POST", "/api/sessions", body);
      sessionId = data.session_id;
      sessionMode = data.info.mode;
      $("pool-label").textContent = `${data.info.pool_size} candidates`;
      $("finish-btn").classList.toggle("hidden", sessionMode === "bracket");
      $("undo-btn").classList.toggle("hidden", sessionMode === "bracket");
      $("undo-btn").disabled = true; // nothing to undo at the start of a fresh session
      $("bracket-tree-live").classList.toggle("hidden", sessionMode !== "bracket");
      showScreen("screen-duel");
      renderPairing(data.pairing);
      if (sessionMode === "bracket") refreshLiveBracketTree();
    } catch (e) {
      $("filter-error").textContent = e.message;
      $("filter-error").classList.remove("hidden");
    } finally {
      $("start-btn").disabled = false;
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
        const { rankings } = await api("GET", `/api/sessions/${sessionId}/results`);
        renderResults(rankings);
      }
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

  // Shared between the per-session results screen and the all-time
  // leaderboard -- same row shape (rank, art, pips, name), the only
  // real difference is what goes in the right-hand stat column, which
  // the caller supplies via `statFor` so each screen can show what's
  // actually meaningful there (session delta-from-1000 vs. all-time
  // games played).
  function renderRankList(containerId, rankings, statFor) {
    const list = $(containerId);
    list.innerHTML = rankings
      .map((c, i) => {
        const { cls, html } = statFor(c);
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
            <div class="rank-rating ${cls}">${html}</div>
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
      row.addEventListener("click", () => openLightbox(c.image_urls, c.name, c.edhrec_url));
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault(); // stop the page from scrolling on Space
          openLightbox(c.image_urls, c.name, c.edhrec_url);
        }
      });
    });
  }

  function renderResults(rankings) {
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

  function renderLeaderboard(rankings) {
    renderRankList("leaderboard-list", rankings, (c) => {
      const games = c.games_played === 1 ? "1 game" : `${c.games_played} games`;
      return { cls: "", html: `${Math.round(c.rating)} <span style="opacity:.6">(${games})</span>` };
    });
    showScreen("screen-leaderboard");
  }

  async function showLeaderboard() {
    try {
      const params = new URLSearchParams();
      if (leaderboardActiveColors.size) params.set("colors", [...leaderboardActiveColors].join(""));
      params.set("color_mode", leaderboardColorMode);
      const { leaderboard } = await api("GET", `/api/leaderboard?${params.toString()}`);
      if (!leaderboard.length) {
        // Distinguish "nothing's ever been rated" from "your color
        // filter excludes everything currently rated" -- the first
        // needs "go play a session," the second just needs a looser
        // filter.
        $("leaderboard-list").innerHTML = leaderboardActiveColors.size
          ? '<div class="spinner-note">No commanders match that color filter yet.</div>'
          : '<div class="spinner-note">No all-time ratings yet — finish a duel session first.</div>';
        showScreen("screen-leaderboard");
        return;
      }
      renderLeaderboard(leaderboard);
    } catch (e) {
      window.alert(e.message);
    }
  }

  function openLightbox(imageUrls, name, edhrecUrl) {
    if (!imageUrls || !imageUrls.length) return;
    $("lightbox-name").textContent = name || "";
    $("lightbox-images").innerHTML = imageUrls
      .map((url) => `<img src="${url}" alt="${name || ""}" />`)
      .join("");
    // EDHREC's own link is always reliable (stored per commander).
    // Moxfield/Archidekt are best-effort generic search links -- their
    // exact deep-link query format can't be verified from this sandbox
    // (no live network access), worth a quick click-test once deployed.
    const query = encodeURIComponent(name || "");
    const links = [
      edhrecUrl ? `<a href="${edhrecUrl}" target="_blank" rel="noopener">View on EDHREC →</a>` : "",
      name ? `<a href="https://www.moxfield.com/decks?q=${query}" target="_blank" rel="noopener">Search Moxfield</a>` : "",
      name ? `<a href="https://archidekt.com/search/decks?q=${query}" target="_blank" rel="noopener">Search Archidekt</a>` : "",
    ]
      .filter(Boolean)
      .join("");
    $("lightbox-links").innerHTML = links;
    $("lightbox").classList.remove("hidden");
  }

  function closeLightbox() {
    $("lightbox").classList.add("hidden");
    $("lightbox-images").innerHTML = "";
    $("lightbox-links").innerHTML = "";
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
  $("lightbox-close").addEventListener("click", closeLightbox);
  $("lightbox").addEventListener("click", (e) => {
    if (e.target.id === "lightbox") closeLightbox(); // click on backdrop, not the card image itself
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeLightbox();
      return;
    }
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
  $("again-btn").addEventListener("click", () => {
    sessionId = null;
    currentPairing = null;
    showScreen("screen-intro");
    refreshPoolPreview();
  });
  $("start-btn").addEventListener("click", startSession);
  $("filter-reset-btn").addEventListener("click", () => {
    activeColors.clear();
    colorMode = "subset";
    maxDecks = 10000;
    poolSize = 40;

    renderColorChips("color-chips", activeColors, refreshPoolPreview);
    document.querySelectorAll("#color-mode-toggle .segmented-btn").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.mode === "subset"));
    });
    $("max-decks-slider").value = maxDecks;
    $("max-decks-input").value = maxDecks;
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

    refreshPoolPreview();
  });
  $("leaderboard-link").addEventListener("click", showLeaderboard);
  $("results-leaderboard-link").addEventListener("click", showLeaderboard);
  $("leaderboard-back-btn").addEventListener("click", () => {
    showScreen("screen-intro");
    refreshPoolPreview();
  });
  $("leaderboard-reset-btn").addEventListener("click", () => {
    leaderboardActiveColors.clear();
    leaderboardColorMode = "subset";
    // Rebuild the chips fresh (renderColorChips always starts every
    // chip unpressed) and reset the toggle's visual state directly,
    // since wireColorModeToggle only wires clicks, it has no reset of
    // its own.
    renderColorChips("leaderboard-color-chips", leaderboardActiveColors, showLeaderboard);
    document.querySelectorAll("#leaderboard-color-mode-toggle .segmented-btn").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.mode === "subset"));
    });
    showLeaderboard();
  });
  $("leaderboard-reset-data-btn").addEventListener("click", async () => {
    // Destructive and irreversible -- confirm before touching the
    // server, same pattern as window.alert() for errors elsewhere in
    // this file (a native browser dialog, not a custom in-app one).
    const confirmed = window.confirm(
      "This permanently erases every commander's all-time rating and games-played " +
        "count. Past session results themselves aren't affected -- only the all-time " +
        "leaderboard built from them. This can't be undone. Continue?"
    );
    if (!confirmed) return;
    try {
      await api("DELETE", "/api/leaderboard");
      showLeaderboard();
    } catch (e) {
      window.alert(e.message);
    }
  });

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

  wireColorModeToggle("color-mode-toggle", (m) => { colorMode = m; }, refreshPoolPreview);
  wireColorModeToggle("leaderboard-color-mode-toggle", (m) => { leaderboardColorMode = m; }, showLeaderboard);
  wireColorModeToggle("mode-toggle", setFilterMode, () => {});

  renderColorChips("color-chips", activeColors, refreshPoolPreview);
  renderColorChips("leaderboard-color-chips", leaderboardActiveColors, showLeaderboard);
  refreshPoolPreview();
  showScreen("screen-intro");
})();
