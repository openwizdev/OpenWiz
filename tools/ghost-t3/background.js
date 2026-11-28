"use strict";

var ROUTES = { complete: true, feedback: true };
var rulePort = null;
var ruleReady = Promise.resolve();

function ensureRule(port) {
  if (rulePort === port) return ruleReady;
  var next = ruleReady.catch(function () {}).then(function () {
    return chrome.declarativeNetRequest.updateSessionRules({
      removeRuleIds: [1],
      addRules: [{
        id: 1,
        priority: 1,
        action: {
          type: "modifyHeaders",
          requestHeaders: [{ header: "Origin", operation: "remove" }],
        },
        condition: {
          regexFilter: "^http://127\\.0\\.0\\.1:" + port + "/ghost/v1/(complete|feedback)$",
          initiatorDomains: [chrome.runtime.id],
          tabIds: [-1],
          resourceTypes: ["xmlhttprequest"],
        },
      }],
    });
  });
  rulePort = port;
  ruleReady = next;
  return next.catch(function (error) {
    if (rulePort === port) rulePort = null;
    throw error;
  });
}

chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  if (!sender || sender.id !== chrome.runtime.id || !sender.tab) {
    sendResponse({ status: 403, body: null });
    return false;
  }
  relay(message).then(sendResponse, function () {
    sendResponse({ status: 0, body: null });
  });
  return true;
});

function relay(message) {
  if (!message || !ROUTES[message.route] || !message.body || typeof message.body !== "object") {
    return Promise.resolve({ status: 400, body: null });
  }
  return chrome.storage.local.get({ token: "", port: 17417 }).then(function (stored) {
    var port = stored.port;
    if (typeof stored.token !== "string" || stored.token.length === 0) {
      return { status: 401, body: null };
    }
    if (typeof port !== "number" || !Number.isInteger(port) || port < 1 || port > 65535) {
      return { status: 400, body: null };
    }
    return ensureRule(port).then(function () {
      return fetch("http://127.0.0.1:" + port + "/ghost/v1/" + message.route, {
        method: "POST",
        redirect: "error",
        credentials: "omit",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + stored.token,
        },
        body: JSON.stringify(message.body),
      });
    }).then(function (response) {
      return response.json().then(function (body) {
        return { status: response.status, body: body };
      }, function () {
        return { status: response.status, body: null };
      });
    }, function () {
      return { status: 0, body: null };
    });
  });
}
