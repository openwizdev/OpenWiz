"use strict";

(function () {
  var tokenInput = document.querySelector("#token");
  var portInput = document.querySelector("#port");
  var statusEl = document.querySelector("#status");

  chrome.storage.local.get({ token: "", port: 17417 }, function (stored) {
    tokenInput.value = typeof stored.token === "string" ? stored.token : "";
    portInput.value = String(stored.port);
  });

  document.querySelector("form").addEventListener("submit", function (event) {
    event.preventDefault();
    var nextPort = Number(portInput.value);
    if (!Number.isInteger(nextPort) || nextPort < 1 || nextPort > 65535) {
      statusEl.textContent = "Port must be from 1 to 65535.";
      return;
    }
    if (tokenInput.value.length === 0) {
      statusEl.textContent = "A pairing token is required.";
      return;
    }
    chrome.storage.local.set({ token: tokenInput.value, port: nextPort }, function () {
      statusEl.textContent = "Saved on this browser.";
    });
  });
})();
