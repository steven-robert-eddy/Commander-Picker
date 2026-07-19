// Kicks off the initial screen, loaded last once every module has
// registered itself on window.CP. Each feature module wires its own
// screen's DOM at load time (color chips, etc.), so there's nothing
// left to do here but pick the landing screen.
(function () {
  "use strict";

  window.CP.showScreen("screen-home");
})();
