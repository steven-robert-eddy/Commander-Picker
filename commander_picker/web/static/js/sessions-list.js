// "My sessions" screen. Resuming a session is handled by picker.js
// (CP.resumeSession) since it mutates that module's own private session
// state and re-enters its own duel/results rendering -- this module
// just lists sessions and dispatches the resume click.
(function () {
  "use strict";

  const { $, api, showScreen } = window.CP;

  async function showSessions() {
    try {
      const { sessions } = await api("GET", "/api/sessions");
      renderSessionsList(sessions);
      showScreen("screen-sessions");
    } catch (e) {
      window.alert(e.message);
    }
  }

  function renderSessionsList(sessionList) {
    const list = $("sessions-list");
    if (!sessionList.length) {
      list.innerHTML = '<div class="spinner-note">No sessions yet — start a duel or bracket from the filter screen.</div>';
      return;
    }
    list.innerHTML = sessionList
      .map((s) => {
        const modeLabel = s.mode === "bracket" ? "Bracket" : "Duel";
        const actionLabel = s.status === "active" ? "Resume →" : "View results →";
        return `
          <div class="session-row" data-id="${s.id}">
            <div class="session-info">
              <div class="session-desc">${s.description || "No filters"}</div>
              <div class="session-meta">${modeLabel} · ${s.rounds_completed}/${s.target_rounds} rounds · ${s.pool_size} candidates · ${s.status}</div>
            </div>
            <button class="ghost-btn session-action" type="button">${actionLabel}</button>
          </div>
        `;
      })
      .join("");
    list.querySelectorAll(".session-row").forEach((row) => {
      row.querySelector(".session-action").addEventListener("click", () => window.CP.resumeSession(row.dataset.id));
    });
  }

  $("sessions-back-btn").addEventListener("click", () => showScreen("screen-home"));

  window.CP.showSessions = showSessions;
})();
