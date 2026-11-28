import { acceptAction, bridgeUrl, canAct, emptyState, selectPending, tabGrantable } from "./policy.mjs";

const $ = (id) => document.getElementById(id);
const ACT_MS = 700;
const BRIDGE_TIMEOUT_MS = 125000;
let pending = [];
let sending = false;
let turnSeq = 0;

function call(message) {
  return chrome.runtime.sendMessage(message).then((response) => response || { ok: false, error: "The extension did not answer." });
}

function note(text) {
  $("notice").textContent = text || "";
}

function connectError(text) {
  $("connect-error").textContent = text || "";
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab || null;
}

async function tabById(tabId) {
  if (tabId == null) return null;
  try {
    return (await chrome.tabs.get(tabId)) || null;
  } catch {
    return null;
  }
}

async function sessionId() {
  const bag = await chrome.storage.session.get("sessionId");
  if (typeof bag.sessionId === "string" && bag.sessionId) return bag.sessionId;
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  const id = `sess-${[...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
  await chrome.storage.session.set({ sessionId: id });
  return id;
}

async function post(route, body) {
  const url = bridgeUrl($("bridge").value.trim());
  const token = $("token").value.trim();
  if (!url) return { ok: false, error: "The bridge address must be http://127.0.0.1 or http://localhost with a port." };
  if (!token) return { ok: false, error: "Paste the pairing token from the bridge." };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), BRIDGE_TIMEOUT_MS);
  try {
    const res = await fetch(`${url}/chrome/v1/${route}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify(body),
      signal: controller.signal
    });
    let payload = null;
    try {
      payload = await res.json();
    } catch {
      payload = null;
    }
    if (!res.ok) {
      const message = payload && payload.refusal && payload.refusal.message;
      return { ok: false, error: message || "The bridge refused the request." };
    }
    return { ok: true, body: payload };
  } catch (error) {
    if (error && error.name === "AbortError") return { ok: false, error: "The bridge did not answer in time." };
    return { ok: false, error: "The local bridge is not running." };
  } finally {
    clearTimeout(timer);
  }
}

function paint(state) {
  const current = state || emptyState();
  $("acting").hidden = !current.acting;
  const list = $("grant-list");
  list.replaceChildren();
  const entries = Object.entries(current.grants || {});
  for (const [id, grant] of entries) {
    const item = document.createElement("li");
    const span = document.createElement("span");
    span.textContent = grant.title || grant.origin || `Tab ${id}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = "Revoke";
    button.addEventListener("click", () => call({ type: "revoke-tab", tabId: Number(id) }));
    item.append(span, button);
    list.appendChild(item);
  }
  if (current.session) {
    const item = document.createElement("li");
    const span = document.createElement("span");
    span.textContent = "This browser session";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = "Revoke";
    button.addEventListener("click", () => call({ type: "revoke-session" }));
    item.append(span, button);
    list.appendChild(item);
  }
  if (!list.children.length) {
    const item = document.createElement("li");
    item.textContent = "Nothing is allowed yet.";
    list.appendChild(item);
  }
}

async function paintTab() {
  const tab = await activeTab();
  if (!tab) {
    $("current-tab").textContent = "No active tab.";
    return;
  }
  const title = tab.title || tab.url || "This tab";
  $("current-tab").textContent = tabGrantable(tab.url) ? title : "This tab cannot be granted.";
}

function showApp(on) {
  $("connect").hidden = on;
  $("app").hidden = !on;
  $("disconnect").hidden = !on;
  $("status").textContent = on ? "Connected to the local bridge" : "Not connected";
}

function appendMessage(role, text, actions, waiting, origin = null) {
  const empty = $("log").querySelector(".empty");
  if (empty) empty.remove();
  const item = document.createElement("article");
  item.className = role;
  const body = document.createElement("p");
  body.textContent = text;
  item.appendChild(body);
  const statuses = [];
  for (const action of actions || []) {
    const card = document.createElement("div");
    card.className = "action";
    const label = document.createElement("p");
    label.textContent = action.description || action.op;
    const status = document.createElement("p");
    status.className = "action-status";
    status.textContent = origin && origin.closed
      ? origin.closed
      : waiting ? "Waiting for permission" : "Running";
    card.append(label, status);
    if (waiting && origin && origin.tabId != null) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Allow this tab and run";
      const entry = { tabId: origin.tabId, turnId: origin.turnId, action, status, button };
      button.addEventListener("click", () => allowAndRun(entry));
      card.appendChild(button);
      pending.push(entry);
    }
    statuses.push(status);
    item.appendChild(card);
  }
  $("log").appendChild(item);
  item.scrollIntoView({ block: "end" });
  return statuses;
}

function offerSite(status, url, onRetry) {
  if (status.parentElement.querySelector(".site")) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "site secondary";
  button.textContent = "Allow this site in Chrome";
  button.addEventListener("click", async () => {
    const pattern = `${new URL(url).origin}/*`;
    const ok = await chrome.permissions.request({ origins: [pattern] });
    if (ok) {
      button.remove();
      status.textContent = "Site allowed. Retrying…";
      if (onRetry) await onRetry();
    } else {
      status.textContent = "Chrome did not grant this site.";
    }
  });
  status.parentElement.appendChild(button);
}

async function retryWithTab(tabId, action, status, allowButton) {
  const tab = await tabById(tabId);
  if (!tab) {
    status.textContent = "The original tab is closed.";
    return;
  }
  if (allowButton) allowButton.disabled = true;
  const ok = await runOne(tab.id, action, status, tab.url, allowButton);
  if (ok && allowButton) {
    allowButton.hidden = true;
    pending = pending.filter((item) => item.button !== allowButton);
  } else if (allowButton) {
    allowButton.disabled = false;
  }
}

async function runOne(tabId, action, status, url, allowButton = null) {
  const accepted = acceptAction(action);
  if (!accepted) {
    status.textContent = "The action was refused.";
    return false;
  }
  status.textContent = "Running";
  const begun = await call({ type: "begin-act", tabId });
  if (!begun.ok) {
    status.textContent = "Grant this tab or this session first.";
    return false;
  }
  const started = Date.now();
  let succeeded = false;
  try {
    if (accepted.op === "navigate") {
      if (url && tabGrantable(url)) {
        try {
          await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
          await chrome.tabs.sendMessage(tabId, { type: "banner" });
        } catch {
        }
      }
      await chrome.tabs.update(tabId, { url: accepted.url });
      status.textContent = `Opening ${accepted.url}`;
      succeeded = true;
      return true;
    }
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    const result = await chrome.tabs.sendMessage(tabId, { type: "act", action: accepted });
    if (result && result.ok) {
      status.textContent = result.detail || "Done";
      succeeded = true;
      return true;
    }
    status.textContent = result && result.error === "permission_required"
      ? "Grant this tab or this session first."
      : (result && result.error) || "The action failed.";
    return false;
  } catch {
    const live = await tabById(tabId);
    if (!live) {
      status.textContent = "The original tab is closed.";
      return false;
    }
    status.textContent = "The tab could not be reached.";
    const targetUrl = live.url || url;
    if (accepted.op !== "navigate" && targetUrl && tabGrantable(targetUrl)) {
      offerSite(status, targetUrl, () => retryWithTab(tabId, action, status, allowButton));
    }
    return false;
  } finally {
    if (succeeded) {
      const wait = ACT_MS - (Date.now() - started);
      if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
    }
    await call({ type: "end-act", tabId });
  }
}

async function ensureOrigin(tab) {
  if (!tabGrantable(tab.url)) return false;
  const pattern = `${new URL(tab.url).origin}/*`;
  if (await chrome.permissions.contains({ origins: [pattern] })) return true;
  return chrome.permissions.request({ origins: [pattern] });
}

async function grantTabFor(tab) {
  if (!tab || !tabGrantable(tab.url)) {
    note("Only an http or https tab can be granted.");
    return null;
  }
  if (!(await ensureOrigin(tab))) {
    note("Chrome did not grant this site. The agent cannot act here yet.");
    return null;
  }
  const granted = await call({ type: "grant-tab", tab: { id: tab.id, url: tab.url, title: tab.title || "" } });
  if (!granted.ok) {
    note(granted.error || "The tab was not granted.");
    return null;
  }
  note("");
  return tab;
}

async function grantActive(kind) {
  const tab = await activeTab();
  if (kind === "tab") return grantTabFor(tab);
  const siteNeeded = Boolean(tab && tabGrantable(tab.url));
  const siteOk = siteNeeded ? await ensureOrigin(tab) : true;
  const granted = await call({ type: "grant-session" });
  if (!granted.ok) {
    note(granted.error || "The session was not granted.");
    return null;
  }
  if (siteNeeded && !siteOk) {
    note("Session allowed, but Chrome did not grant this site yet.");
    return null;
  }
  note("");
  return tab;
}

async function runQueued(tab) {
  if (!tab) return;
  const queued = selectPending(pending, tab.id);
  for (const item of queued) {
    if (!item.button.isConnected) {
      pending = pending.filter((entry) => entry !== item);
      continue;
    }
    item.button.disabled = true;
    const ok = await runOne(tab.id, item.action, item.status, tab.url, item.button);
    if (ok) {
      item.button.hidden = true;
      pending = pending.filter((entry) => entry !== item);
    } else {
      item.button.disabled = false;
      break;
    }
  }
}

async function allowAndRun(entry) {
  if (entry.button.disabled) return;
  entry.button.disabled = true;
  try {
    const tab = await tabById(entry.tabId);
    if (!tab) {
      entry.status.textContent = "The original tab is closed.";
      entry.button.hidden = true;
      pending = pending.filter((item) => item !== entry);
      return;
    }
    const granted = await grantTabFor(tab);
    if (!granted) return;
    const ok = await runOne(tab.id, entry.action, entry.status, tab.url, entry.button);
    if (ok) {
      entry.button.hidden = true;
      pending = pending.filter((item) => item !== entry);
    }
  } finally {
    if (!entry.button.hidden) entry.button.disabled = false;
  }
}

async function collectPage(tab) {
  if (!tab || !tabGrantable(tab.url)) return { page: null, note: "This tab has no page to attach." };
  const base = { url: tab.url || "", title: tab.title || "", selection: "", text: "" };
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    const result = await chrome.tabs.sendMessage(tab.id, { type: "read" });
    if (result && result.ok && result.page) return { page: result.page, note: "" };
  } catch {
    return { page: base, note: "The page text could not be read. The address and title were sent." };
  }
  return { page: base, note: "The page text could not be read. The address and title were sent." };
}

async function onSend(event) {
  event.preventDefault();
  if (sending) return;
  const text = $("text").value.trim();
  if (!text) return;
  sending = true;
  $("send").disabled = true;
  $("text").value = "";
  note("");
  appendMessage("user", text);
  const originTab = await activeTab();
  const turnId = ++turnSeq;
  let page = null;
  if ($("include-page").checked) {
    const collected = await collectPage(originTab);
    page = collected.page;
    if (collected.note) note(collected.note);
  }
  const response = await post("chat", {
    session_id: await sessionId(),
    agent: $("agent").value,
    text,
    page
  });
  sending = false;
  $("send").disabled = false;
  if (!response.ok) {
    appendMessage("agent", response.error || "The bridge did not answer.");
    return;
  }
  const actions = Array.isArray(response.body.actions) ? response.body.actions : [];
  const tab = originTab && originTab.id != null ? await tabById(originTab.id) : null;
  if (!tab && actions.length > 0) {
    const closed = originTab ? "The original tab is closed." : "No active tab.";
    appendMessage("agent", response.body.text || "", actions, false, { closed });
    return;
  }
  const state = await call({ type: "get-state" });
  const allowed = Boolean(tab && state.ok && canAct(state.state, tab.id));
  const statuses = appendMessage(
    "agent",
    response.body.text || "",
    actions,
    !allowed && actions.length > 0,
    tab ? { tabId: tab.id, turnId } : null
  );
  if (!allowed || !tab) return;
  for (let index = 0; index < actions.length; index += 1) {
    const ok = await runOne(tab.id, actions[index], statuses[index], tab.url);
    if (!ok) break;
  }
}

async function connect(event) {
  if (event) event.preventDefault();
  connectError("");
  const url = bridgeUrl($("bridge").value.trim());
  if (!url) {
    connectError("Use http://127.0.0.1 or http://localhost and a port.");
    return;
  }
  $("bridge").value = url;
  const health = await post("health", {});
  if (!health.ok) {
    connectError(health.error);
    return;
  }
  const agents = await post("agents", {});
  if (!agents.ok) {
    connectError(agents.error);
    return;
  }
  const select = $("agent");
  select.replaceChildren();
  for (const row of agents.body.agents || []) {
    const option = document.createElement("option");
    option.value = row.id;
    option.textContent = row.name || row.id;
    select.appendChild(option);
  }
  if (!select.options.length) {
    connectError("The bridge has no agent.");
    return;
  }
  await chrome.storage.local.set({
    bridge: url,
    token: $("token").value.trim(),
    includePage: $("include-page").checked
  });
  showApp(true);
  if (!$("log").childElementCount) {
    const item = document.createElement("p");
    item.className = "empty";
    item.textContent = "Ask about this page, or tell the agent to click, type or open a link.";
    $("log").appendChild(item);
  }
  const state = await call({ type: "get-state" });
  paint(state.ok ? state.state : emptyState());
  await paintTab();
}

async function restore() {
  const saved = await chrome.storage.local.get(["bridge", "token", "includePage"]);
  if (typeof saved.bridge === "string") $("bridge").value = saved.bridge;
  if (typeof saved.token === "string") $("token").value = saved.token;
  if (typeof saved.includePage === "boolean") $("include-page").checked = saved.includePage;
  if ($("token").value.trim()) await connect();
}

$("connect-form").addEventListener("submit", connect);
$("composer").addEventListener("submit", onSend);
$("text").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("composer").requestSubmit();
  }
});
$("disconnect").addEventListener("click", async () => {
  await chrome.storage.local.remove("token");
  $("token").value = "";
  connectError("");
  showApp(false);
});
$("grant-tab").addEventListener("click", async () => {
  const tab = await grantActive("tab");
  if (tab) await runQueued(tab);
});
$("grant-session").addEventListener("click", async () => {
  const tab = await grantActive("session");
  if (tab) await runQueued(tab);
});
$("include-page").addEventListener("change", () => {
  chrome.storage.local.set({ includePage: $("include-page").checked });
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "session" && changes.permission) paint(changes.permission.newValue || emptyState());
});
chrome.tabs.onActivated.addListener(() => paintTab());
chrome.tabs.onUpdated.addListener(() => paintTab());
chrome.tabs.onRemoved.addListener((tabId) => {
  for (const item of pending) {
    if (item.tabId === tabId) {
      item.button.hidden = true;
      item.status.textContent = "The original tab is closed.";
    }
  }
  pending = pending.filter((item) => item.tabId !== tabId);
  paintTab();
});
restore();
