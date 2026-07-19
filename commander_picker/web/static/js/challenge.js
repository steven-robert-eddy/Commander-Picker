// 32-deck challenge tracker screen.
(function () {
  "use strict";

  const { $, api, pipsHTML, showScreen } = window.CP;

  function challengeDisplayName(slug) {
    return slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  // Purely additive nudge on the results screen -- offers to add the
  // winning commander as a candidate for its color combo, but never
  // overwrites/auto-chooses anything. Silent no-op on failure since the
  // results screen itself already rendered fine either way. Called
  // cross-module from picker.js's renderResults/renderBracketResults.
  async function maybeShowChallengeNudge(slug, commanderName) {
    const nudge = $("challenge-nudge");
    nudge.classList.add("hidden");
    if (!slug || !commanderName) return;
    try {
      const { entries } = await api("GET", "/api/challenge");
      const entry = entries.find((e) => e.slug === slug);
      if (!entry || entry.commanders.some((c) => c.name === commanderName)) return;

      $("challenge-nudge-text").textContent = `Add ${commanderName} as an option for ${challengeDisplayName(slug)}?`;
      nudge.classList.remove("hidden");
      $("challenge-nudge-btn").onclick = async () => {
        try {
          await api("POST", `/api/challenge/${encodeURIComponent(slug)}/commanders`, { commander_name: commanderName });
          nudge.classList.add("hidden");
        } catch (e) {
          window.alert(e.message);
        }
      };
    } catch (e) {
      // Non-critical -- the results screen itself still works.
    }
  }

  async function showChallenge(highlightSlug) {
    try {
      const { entries } = await api("GET", "/api/challenge");
      renderChallengeList(entries);
      showScreen("screen-challenge");
      if (highlightSlug) highlightChallengeRow(highlightSlug);
    } catch (e) {
      window.alert(e.message);
    }
  }

  function highlightChallengeRow(slug) {
    const row = $("challenge-list").querySelector(`.challenge-row[data-slug="${slug}"]`);
    if (!row) return;
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    row.classList.add("challenge-row-highlight");
    setTimeout(() => row.classList.remove("challenge-row-highlight"), 1500);
  }

  function renderChallengeList(entries) {
    const list = $("challenge-list");
    list.innerHTML = entries
      .map(
        (e) => `
          <div class="challenge-row" data-slug="${e.slug}">
            <div class="challenge-row-header">
              <div class="challenge-combo">${pipsHTML(e.colors)}<span>${challengeDisplayName(e.slug)}</span></div>
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
          </div>
        `
      )
      .join("");

    list.querySelectorAll(".challenge-row").forEach((row) => {
      const slug = row.dataset.slug;
      const entry = entries.find((e) => e.slug === slug);

      row.querySelector(".challenge-status-select").addEventListener("change", async (ev) => {
        try {
          await api("PUT", `/api/challenge/${encodeURIComponent(slug)}`, { status: ev.target.value, notes: entry.notes });
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
              `/api/challenge/${encodeURIComponent(slug)}/commanders/${encodeURIComponent(candidate.name)}/choose`
            );
            showChallenge();
          } catch (e) {
            window.alert(e.message);
          }
        });
        card.querySelector(".challenge-remove-btn").addEventListener("click", async () => {
          try {
            await api(
              "DELETE",
              `/api/challenge/${encodeURIComponent(slug)}/commanders/${encodeURIComponent(candidate.name)}`
            );
            showChallenge();
          } catch (e) {
            window.alert(e.message);
          }
        });
      });
    });
  }

  // Single search box for the whole challenge screen (not one per
  // combo) -- a commander's own color identity determines which of the
  // 32 combos it belongs to, via /api/challenge/commanders, so there's
  // no "which row" decision for the user to make. Same search-as-you-
  // type pattern as picker.js's custom-list searchCommanders.
  let challengeSearchDebounceTimer = null;

  async function searchChallengeCommanders() {
    const q = $("challenge-search-input").value.trim();
    const resultsEl = $("challenge-search-results");
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
              <span class="autocomplete-item-decks">${r.num_decks.toLocaleString()} decks</span>
            </button>
          `
        )
        .join("");
      resultsEl.querySelectorAll(".autocomplete-item").forEach((btn) => {
        btn.addEventListener("click", async () => {
          try {
            const entry = await api("POST", "/api/challenge/commanders", {
              commander_name: btn.dataset.name,
              color_identity: btn.dataset.colors,
            });
            $("challenge-search-input").value = "";
            resultsEl.classList.add("hidden");
            resultsEl.innerHTML = "";
            showChallenge(entry.slug);
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

  $("challenge-back-btn").addEventListener("click", () => showScreen("screen-home"));
  const challengeSearchInput = $("challenge-search-input");
  challengeSearchInput.addEventListener("input", () => {
    clearTimeout(challengeSearchDebounceTimer);
    challengeSearchDebounceTimer = setTimeout(searchChallengeCommanders, 250);
  });

  Object.assign(window.CP, {
    showChallenge,
    maybeShowChallengeNudge,
  });
})();
