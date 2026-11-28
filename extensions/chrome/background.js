import {
  badgeText,
  beginActing,
  canAct,
  createQueue,
  emptyState,
  endActing,
  grantSession,
  grantTab,
  revokeActing,
  revokeSession,
  revokeTab
} from "./policy.mjs";

const KEY = "permission";
const enqueue = createQueue();

function openPanel() {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
}

openPanel();
chrome.runtime.onInstalled.addListener(openPanel);

async function load() {
  const bag = await chrome.storage.session.get(KEY);
  const state = bag[KEY];
  if (!state || typeof state !== "object" || !state.grants) return emptyState();
  return state;
}

async function save(state) {
  await chrome.storage.session.set({ [KEY]: state });
  const text = badgeText(state);
  await chrome.action.setBadgeText({ text });
  await chrome.action.setBadgeBackgroundColor({ color: text === "ACT" ? "#9f1239" : "#2b2bff" });
  const title = state.acting ? "OpenWiz agent is acting" : "OpenWiz";
  await chrome.action.setTitle({ title });
  if (chrome.action.setBadgeTextColor) {
    chrome.action.setBadgeTextColor({ color: "#ffffff" }).catch(() => {});
  }
  return state;
}

function fromPage(sender) {
  return Boolean(sender && sender.tab);
}

async function handleNow(message, sender) {
  const state = await load();
  if (!message || typeof message !== "object") return { ok: false };
  if (message.type === "get-state") {
    if (fromPage(sender)) return { ok: false };
    return { ok: true, state };
  }
  if (message.type === "grant-tab") {
    if (fromPage(sender)) return { ok: false, error: "permission_required" };
    const next = grantTab(state, message.tab, Date.now());
    if (!next) return { ok: false, error: "This tab cannot be granted." };
    return { ok: true, state: await save(next) };
  }
  if (message.type === "grant-session") {
    if (fromPage(sender)) return { ok: false, error: "permission_required" };
    return { ok: true, state: await save(grantSession(state, Date.now())) };
  }
  if (message.type === "revoke-tab") {
    if (fromPage(sender)) return { ok: false, error: "permission_required" };
    return { ok: true, state: await save(revokeTab(state, message.tabId)) };
  }
  if (message.type === "revoke-session") {
    if (fromPage(sender)) return { ok: false, error: "permission_required" };
    return { ok: true, state: await save(revokeSession(state)) };
  }
  if (message.type === "begin-act") {
    if (fromPage(sender)) return { ok: false, error: "permission_required" };
    const next = beginActing(state, message.tabId, Date.now());
    if (!next) return { ok: false, error: "permission_required" };
    return { ok: true, state: await save(next) };
  }
  if (message.type === "end-act") {
    if (fromPage(sender)) return { ok: false };
    return { ok: true, state: await save(endActing(state, message.tabId)) };
  }
  if (message.type === "can-act") {
    if (!fromPage(sender)) return { ok: false };
    return { ok: Boolean(canAct(state, sender.tab.id)) };
  }
  if (message.type === "revoke-acting") {
    if (!fromPage(sender)) return { ok: false };
    return { ok: true, state: await save(revokeActing(state, sender.tab.id)) };
  }
  return { ok: false };
}

function handle(message, sender) {
  return enqueue(() => handleNow(message, sender));
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handle(message, sender)
    .then(sendResponse)
    .catch(() => sendResponse({ ok: false, error: "The extension could not update permission." }));
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  enqueue(async () => save(revokeTab(await load(), tabId))).catch(() => {});
});
