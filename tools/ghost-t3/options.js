"use strict";

var token = document.querySelector("#token");
var port = document.querySelector("#port");
var status = document.querySelector("#status");

chrome.storage.local.get({ token: "", port: 17417 }, function (stored) {
  token.value = typeof stored.token === "string" ? stored.token : "";
  port.value = String(stored.port);
});

document.querySelector("form").addEventListener("submit", function (event) {
  event.preventDefault();
  var nextPort = Number(port.value);
  if (!Number.isInteger(nextPort) || nextPort < 1 || nextPort > 65535) {
    status.textContent = "Port must be from 1 to 65535.";
    return;
  }
  if (token.value.length === 0) {
    status.textContent = "A pairing token is required.";
    return;
  }
  chrome.storage.local.set({ token: token.value, port: nextPort }, function () {
    status.textContent = "Saved on this browser.";
  });
});
