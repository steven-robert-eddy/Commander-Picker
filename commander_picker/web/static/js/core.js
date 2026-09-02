// Shared utilities every screen module reads off window.CP. Loaded
// first (see index.html's <script> order) so every other module can
// safely destructure these at its own top-level -- core.js has no
// dependency on anything else, so there's no load-order hazard here.
//
// Convention for the rest of the modules: a *cross-module* function
// (one defined in a different screen's own file, e.g. picker.js
// calling something from challenge.js) must always be called as
// `window.CP.foo(...)` at the call site, never destructured into a
// local const at module-load time -- destructuring only works safely
// for names that are already attached to CP by the time the
// destructuring module's own <script> runs, and feature modules don't
// all load in dependency order (see e.g. picker.js's results
// rendering needing challenge.js's maybeShowChallengeNudge, even
// though picker.js's <script> tag comes first).
(function () {
  "use strict";

  window.CP = window.CP || {};

  const MANA_ORDER = ["W", "U", "B", "R", "G", "C"];
  const $ = (id) => document.getElementById(id);

  // WotC's official Commander Bracket names -- mirrors the 1-5 scale
  // db.py's _apply_commander_detail derives from EDHREC's bracket_counts.
  const BRACKET_LABELS = { 1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized", 5: "cEDH" };

  // Scryfall's own mana symbol art -- the real sun/water-drop/skull/
  // fireball/tree glyphs players recognize from the cards themselves,
  // not a plain colored circle with a letter in it.
  const MANA_SYMBOL_BASE_URL = "https://svgs.scryfall.io/card-symbols/";

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
  // wiring function, multiple independent instances (duel-pool filter,
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

  const SCREEN_IDS = [
    "screen-home",
    "screen-intro",
    "screen-duel",
    "screen-results",
    "screen-leaderboard",
    "screen-sessions",
    "screen-challenge",
    "screen-set-challenge",
    "screen-pod",
    "screen-guess-game",
  ];

  function showScreen(id) {
    SCREEN_IDS.forEach((s) => {
      $(s).classList.toggle("hidden", s !== id);
    });
    $("header-home-btn").classList.toggle("hidden", id === "screen-home");
    $("phase-label").textContent =
      id === "screen-home" ? "Home"
      : id === "screen-intro" ? "Filter"
      : id === "screen-duel" ? "Dueling"
      : id === "screen-results" ? "Results"
      : id === "screen-sessions" ? "Sessions"
      : id === "screen-challenge" ? "32-Deck Challenge"
      : id === "screen-set-challenge" ? "Set Challenge"
      : id === "screen-pod" ? "Pod Tracker"
      : id === "screen-guess-game" ? "Guess the Commander"
      : "Leaderboard";
  }

  // Owned/wishlist collection toggle, shared by rank-row rendering and
  // the lightbox -- cycles none -> owned -> wishlist -> none on click.
  // Text labels, not icon glyphs, to match this app's established
  // mono-label restraint elsewhere.
  const FAV_CYCLE = { none: "owned", owned: "wishlist", wishlist: "none" };
  const FAV_LABELS = { none: "+ Fav", owned: "Owned", wishlist: "Wishlist" };

  function favBtnHTML(status) {
    const s = status || "none";
    return `<button class="fav-btn" type="button" data-status="${s}" aria-pressed="${s !== "none"}">${FAV_LABELS[s]}</button>`;
  }

  // `setStatus` lets the caller keep its own copy of the commander's
  // favorite_status in sync (a rank-row's own data, or the lightbox's
  // currently-open commander) without this helper needing to know
  // where that state actually lives -- same reasoning as statFor below.
  function wireFavBtn(btn, name, setStatus) {
    if (!btn) return;
    btn.addEventListener("click", (e) => {
      e.stopPropagation(); // rank rows with art also open the lightbox on click
      const current = btn.dataset.status;
      const next = FAV_CYCLE[current];
      btn.dataset.status = next;
      btn.textContent = FAV_LABELS[next];
      btn.setAttribute("aria-pressed", String(next !== "none"));
      setStatus(next === "none" ? null : next);
      // commander_name travels in the body/query, never a {name} path
      // segment -- several real commander names contain "/" (double-
      // faced/Partner pairs), which a path segment can't reliably
      // round-trip even percent-encoded.
      const request =
        next === "none"
          ? api("DELETE", `/api/favorites?commander_name=${encodeURIComponent(name)}`)
          : api("PUT", "/api/favorites", { commander_name: name, status: next });
      request.catch(() => {
        // Revert on failure -- the button already shows the optimistic
        // new state, so a failed request needs to visibly undo it
        // rather than silently drift out of sync with the server.
        btn.dataset.status = current;
        btn.textContent = FAV_LABELS[current];
        btn.setAttribute("aria-pressed", String(current !== "none"));
        setStatus(current === "none" ? null : current);
      });
    });
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
        // power_level only exists on session-results rows (RankedCommander),
        // not the all-time leaderboard's GlobalRanking -- absent there, so
        // this simply renders nothing for that call site.
        const powerBadge = c.power_level
          ? `<span class="tag power-tag">Bracket ${c.power_level} · ${BRACKET_LABELS[c.power_level]}</span>`
          : "";
        return `
          <div class="rank-row ${i === 0 ? "top1" : ""} ${hasArt ? "has-art" : ""}" data-idx="${i}" ${interactiveAttrs}>
            <div class="rank-num">${i + 1}</div>
            <div class="rank-name-line">
              ${thumb}
              <div class="pips">${pipsHTML(c.color_identity)}</div>
              <div class="rank-name">${c.name}</div>
              ${powerBadge}
              ${favBtnHTML(c.favorite_status)}
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
      row.addEventListener("click", () => openLightbox(c.image_urls, c.name, c.edhrec_url, c.favorite_status, (s) => (c.favorite_status = s)));
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault(); // stop the page from scrolling on Space
          openLightbox(c.image_urls, c.name, c.edhrec_url, c.favorite_status, (s) => (c.favorite_status = s));
        }
      });
    });
    // Every row gets a favorite toggle, not just ones with art -- keep
    // this a separate pass from the has-art loop above rather than
    // merging them, since the two conditions (has art / has a fav-btn)
    // are independent.
    list.querySelectorAll(".rank-row").forEach((row) => {
      const c = rankings[Number(row.dataset.idx)];
      wireFavBtn(row.querySelector(".fav-btn"), c.name, (s) => (c.favorite_status = s));
    });
  }

  function openLightbox(imageUrls, name, edhrecUrl, favoriteStatus, onFavoriteChange) {
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
    $("lightbox-links").innerHTML = links + (name ? favBtnHTML(favoriteStatus) : "");
    if (name) {
      wireFavBtn($("lightbox-links").querySelector(".fav-btn"), name, (s) => {
        if (onFavoriteChange) onFavoriteChange(s);
      });
    }
    $("lightbox").classList.remove("hidden");
  }

  function closeLightbox() {
    $("lightbox").classList.add("hidden");
    $("lightbox-images").innerHTML = "";
    $("lightbox-links").innerHTML = "";
  }

  $("header-home-btn").addEventListener("click", () => showScreen("screen-home"));

  $("lightbox-close").addEventListener("click", closeLightbox);
  $("lightbox").addEventListener("click", (e) => {
    if (e.target.id === "lightbox") closeLightbox(); // click on backdrop, not the card image itself
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeLightbox();
  });

  Object.assign(window.CP, {
    $,
    api,
    pipsHTML,
    manaCostHTML,
    MANA_SYMBOL_BASE_URL,
    BRACKET_LABELS,
    renderColorChips,
    wireColorModeToggle,
    showScreen,
    renderRankList,
    openLightbox,
    closeLightbox,
  });
})();
