// Set challenge tracker screen -- like challenge.js's 32-deck
// color-identity challenge, but one row per EDHREC set release
// instead of per color combo. Two real differences from challenge.js:
//
// 1. The row list is data-driven (currently 100+ entries, grows every
//    `update-data --discover-sets`), not a fixed 32 -- so there's a
//    client-side name filter to narrow which rows are shown.
// 2. A commander can't be auto-routed to "the" set it belongs to the
//    way color identity always maps to exactly one of the 32 combos
//    (see challenge.js's single global search box) -- so each row
//    gets its own scoped search instead, toggled open on demand
//    rather than fetched/rendered for all rows up front.
(function () {
  "use strict";

  const { $, api, pipsHTML, showScreen } = window.CP;

  let entriesCache = null; // last GET /api/set-challenge result, reused by the name filter
  let openSearchSlug = null; // at most one row's inline search box open at a time

  async function showSetChallenge(highlightSlug) {
    try {
      const { entries } = await api("GET", "/api/set-challenge");
      entriesCache = entries;
      openSearchSlug = null;
      renderSetChallengeList(entries);
      showScreen("screen-set-challenge");
      if (highlightSlug) highlightSetChallengeRow(highlightSlug);
    } catch (e) {
      window.alert(e.message);
    }
  }

  function highlightSetChallengeRow(slug) {
    const row = $("set-challenge-list").querySelector(`.challenge-row[data-slug="${slug}"]`);
    if (!row) return;
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    row.classList.add("challenge-row-highlight");
    setTimeout(() => row.classList.remove("challenge-row-highlight"), 1500);
  }

  function renderSetChallengeList(entries) {
    const list = $("set-challenge-list");
    list.innerHTML = entries
      .map(
        (e) => `
          <div class="challenge-row" data-slug="${e.slug}">
            <div class="challenge-row-header">
              <span>${e.name}</span>
              <select class="challenge-status-select">
                <option value="not_started" ${e.status === "not_started" ? "selected" : ""}>Not started</option>
                <option value="planning" ${e.status === "planning" ? "selected" : ""}>Planning</option>
                <option value="building" ${e.status === "building" ? "selected" : ""}>Building</option>
                <option value="complete" ${e.status === "complete" ? "selected" : ""}>Complete</option>
              </select>
            </div>
            <div class="challenge-commanders">
              ${e.commanders
                .map((c, i) => {
                  const hasArt = c.image_urls && c.image_urls.length;
                  const thumb = hasArt
                    ? `<div class="challenge-candidate-thumb-group">${c.image_urls
                        .map((url) => `<img class="challenge-candidate-thumb" src="${url}" alt="" loading="lazy" onerror="this.remove()" />`)
                        .join("")}</div>`
                    : "";
                  return `
                    <div class="challenge-candidate ${c.is_chosen ? "chosen" : ""}" data-idx="${i}">
                      ${thumb}
                      <div class="challenge-candidate-info">
                        ${pipsHTML(c.color_identity || "")}
                        <span class="challenge-candidate-name">${c.name}</span>
                      </div>
                      <div class="challenge-candidate-actions">
                        <button type="button" class="challenge-choose-btn" title="Mark as chosen">${c.is_chosen ? "★" : "☆"}</button>
                        <button type="button" class="challenge-remove-btn" title="Remove">✕</button>
                      </div>
                    </div>
                  `;
                })
                .join("")}
            </div>
            <div class="challenge-add-row">
              <button type="button" class="ghost-btn set-challenge-add-toggle">+ Add a commander from this set</button>
              <div class="autocomplete-wrap hidden set-challenge-add-wrap">
                <input type="text" class="num-input challenge-add-input set-challenge-add-input" placeholder="Search this set…" autocomplete="off" />
                <div class="autocomplete-dropdown hidden set-challenge-add-results"></div>
              </div>
            </div>
          </div>
        `
      )
      .join("");

    list.querySelectorAll(".challenge-row").forEach((row) => wireSetChallengeRow(row, entries));
  }

  function wireSetChallengeRow(row, entries) {
    const slug = row.dataset.slug;
    const entry = entries.find((e) => e.slug === slug);

    row.querySelector(".challenge-status-select").addEventListener("change", async (ev) => {
      try {
        await api("PUT", `/api/set-challenge/${encodeURIComponent(slug)}`, { status: ev.target.value, notes: entry.notes });
      } catch (e) {
        window.alert(e.message);
      }
    });

    row.querySelectorAll(".challenge-candidate").forEach((card) => {
      const candidate = entry.commanders[Number(card.dataset.idx)];
      card.querySelector(".challenge-choose-btn").addEventListener("click", async () => {
        try {
          await api(
            "POST",
            `/api/set-challenge/${encodeURIComponent(slug)}/commanders/${encodeURIComponent(candidate.name)}/choose`
          );
          showSetChallenge();
        } catch (e) {
          window.alert(e.message);
        }
      });
      card.querySelector(".challenge-remove-btn").addEventListener("click", async () => {
        try {
          await api(
            "DELETE",
            `/api/set-challenge/${encodeURIComponent(slug)}/commanders/${encodeURIComponent(candidate.name)}`
          );
          showSetChallenge();
        } catch (e) {
          window.alert(e.message);
        }
      });
    });

    wireSetChallengeAddRow(row, slug);
  }

  // Scoped, per-row search -- only fetched/rendered when this row's
  // "+ Add" toggle is opened, not for all 100+ rows up front. Opening
  // one row's search closes any other row's, so at most one dropdown
  // is ever live.
  let searchDebounceTimer = null;

  function wireSetChallengeAddRow(row, slug) {
    const toggle = row.querySelector(".set-challenge-add-toggle");
    const wrap = row.querySelector(".set-challenge-add-wrap");
    const input = row.querySelector(".set-challenge-add-input");
    const resultsEl = row.querySelector(".set-challenge-add-results");

    toggle.addEventListener("click", () => {
      const opening = wrap.classList.contains("hidden");
      if (openSearchSlug && openSearchSlug !== slug) {
        const openRow = $("set-challenge-list").querySelector(`.challenge-row[data-slug="${openSearchSlug}"]`);
        if (openRow) {
          openRow.querySelector(".set-challenge-add-wrap").classList.add("hidden");
          openRow.querySelector(".set-challenge-add-results").classList.add("hidden");
        }
      }
      wrap.classList.toggle("hidden", !opening);
      openSearchSlug = opening ? slug : null;
      if (opening) input.focus();
    });

    input.addEventListener("input", () => {
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = setTimeout(() => searchSetChallengeCommanders(slug, input, resultsEl), 250);
    });
  }

  async function searchSetChallengeCommanders(slug, input, resultsEl) {
    const q = input.value.trim();
    if (!q) {
      resultsEl.classList.add("hidden");
      resultsEl.innerHTML = "";
      return;
    }
    try {
      const { results } = await api(
        "GET",
        `/api/set-challenge/${encodeURIComponent(slug)}/commanders/search?q=${encodeURIComponent(q)}`
      );
      if (!results.length) {
        resultsEl.innerHTML = '<div class="spinner-note" style="padding: 9px 12px;">No matches from this set</div>';
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
        btn.addEventListener("click", async () => {
          try {
            await api("POST", `/api/set-challenge/${encodeURIComponent(slug)}/commanders`, {
              commander_name: btn.dataset.name,
            });
            input.value = "";
            resultsEl.classList.add("hidden");
            resultsEl.innerHTML = "";
            showSetChallenge(slug);
          } catch (e) {
            window.alert(e.message);
          }
        });
      });
      resultsEl.classList.remove("hidden");
    } catch (e) {
      resultsEl.innerHTML = `<div class="spinner-note" style="padding: 9px 12px;">${e.message}</div>`;
      resultsEl.classList.remove("hidden");
    }
  }

  const filterInput = $("set-challenge-filter-input");
  filterInput.addEventListener("input", () => {
    if (!entriesCache) return;
    const q = filterInput.value.trim().toLowerCase();
    const filtered = q ? entriesCache.filter((e) => e.name.toLowerCase().includes(q)) : entriesCache;
    openSearchSlug = null;
    renderSetChallengeList(filtered);
  });

  Object.assign(window.CP, {
    showSetChallenge,
  });
})();
