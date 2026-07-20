// Home screen -- the new landing page. Just dispatches each entry
// card to the relevant screen module's own entry point; loaded after
// all the feature modules so every CP.show* function it calls already
// exists on window.CP by the time these listeners can possibly fire.
(function () {
  "use strict";

  const { $ } = window.CP;

  $("home-picker-card").addEventListener("click", () => window.CP.showFilterScreen());
  $("home-challenge-card").addEventListener("click", () => window.CP.showChallenge());
  $("home-pod-card").addEventListener("click", () => window.CP.showPodTracker());
  $("home-leaderboard-card").addEventListener("click", () => window.CP.showLeaderboard());
  $("home-sessions-card").addEventListener("click", () => window.CP.showSessions());
})();
