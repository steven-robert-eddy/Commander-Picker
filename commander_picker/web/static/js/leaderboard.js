// All-time leaderboard screen. Deliberately separate filter state from
// picker.js's duel-pool filters -- checking "how do my mono-red
// commanders rank all-time" shouldn't also change what colors your
// next duel session gets built from.
(function () {
  "use strict";

  const { $, api, renderColorChips, wireColorModeToggle, showScreen, renderRankList } = window.CP;

  const leaderboardActiveColors = new Set();
  let leaderboardColorMode = "subset";

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

  $("results-leaderboard-link").addEventListener("click", showLeaderboard);
  $("leaderboard-back-btn").addEventListener("click", () => showScreen("screen-home"));
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
    // this codebase (a native browser dialog, not a custom in-app one).
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

  wireColorModeToggle("leaderboard-color-mode-toggle", (m) => { leaderboardColorMode = m; }, showLeaderboard);
  renderColorChips("leaderboard-color-chips", leaderboardActiveColors, showLeaderboard);

  window.CP.showLeaderboard = showLeaderboard;
})();
