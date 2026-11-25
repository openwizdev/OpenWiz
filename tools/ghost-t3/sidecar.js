"use strict";
(function () {
  if (document.documentElement.dataset.openwizGhost === "on") return;
  if (typeof globalThis.__openwizGhostSession !== "string" || globalThis.__openwizGhostSession.length === 0) return;
  document.documentElement.dataset.openwizGhost = "on";
  document.addEventListener("input", function () {
    var next = Number(document.documentElement.dataset.openwizSettled || "0") + 1;
    document.documentElement.dataset.openwizSettled = String(next);
  }, true);
})();
