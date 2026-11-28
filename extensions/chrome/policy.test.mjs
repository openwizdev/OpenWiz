import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import {
  acceptAction, badgeText, beginActing, bridgeUrl, canAct, emptyState,
  endActing, grantSession, grantTab, revokeSession, revokeTab, selectPending, tabGrantable
} from "./policy.mjs";

test("a tab starts closed and a grant is what opens it", () => {
  const tab = { id: 7, url: "https://example.com/docs", title: "Docs" };
  assert.equal(canAct(emptyState(), tab.id), null);
  assert.equal(beginActing(emptyState(), tab.id, 1), null);
  assert.equal(badgeText(emptyState()), "");
  const granted = grantTab(emptyState(), tab, 10);
  assert.equal(canAct(granted, 7), "tab");
  assert.equal(canAct(granted, 8), null);
  const acting = beginActing(granted, 7, 11);
  assert.equal(acting.acting.via, "tab");
  assert.equal(badgeText(acting), "ACT");
  const done = endActing(acting, 7);
  assert.equal(done.acting, null);
  assert.equal(badgeText(done), "ON");
  const revoked = revokeTab(done, 7);
  assert.equal(canAct(revoked, 7), null);
  assert.equal(badgeText(revoked), "");
});

test("a session grant covers other tabs and revoke stops it", () => {
  const session = grantSession(emptyState(), 3);
  assert.equal(canAct(session, 4), "session");
  const acting = beginActing(session, 4, 4);
  assert.equal(acting.acting.via, "session");
  const stopped = revokeSession(acting);
  assert.equal(stopped.session, null);
  assert.equal(stopped.acting, null);
  assert.equal(canAct(stopped, 4), null);
});

test("a tab grant is preferred and revoking the session leaves it", () => {
  const tab = { id: 2, url: "http://127.0.0.1/demo", title: "Demo" };
  const both = grantSession(grantTab(emptyState(), tab, 1), 2);
  assert.equal(beginActing(both, 2, 3).acting.via, "tab");
  const sessionGone = revokeSession(both);
  assert.equal(canAct(sessionGone, 2), "tab");
  assert.equal(grantTab(emptyState(), { id: 1, url: "chrome://extensions", title: "" }, 1), null);
  assert.equal(tabGrantable("https://example.com/a"), true);
  assert.equal(tabGrantable("file:///tmp/page.html"), false);
});

test("actions and bridge addresses are narrowed before use", () => {
  assert.equal(acceptAction({ op: "eval", description: "no" }), null);
  assert.equal(acceptAction({ op: "navigate", url: "javascript:alert(1)", description: "no" }), null);
  assert.equal(acceptAction({ op: "click", description: "Click" }), null);
  assert.equal(acceptAction({ op: "type", description: "Type" }), null);
  assert.equal(acceptAction({ op: "click", text: "Demo", description: "Click Demo" }).op, "click");
  assert.equal(acceptAction({ op: "navigate", url: "https://example.com/docs" }).url, "https://example.com/docs");
  assert.equal(bridgeUrl("http://127.0.0.1:17418"), "http://127.0.0.1:17418");
  assert.equal(bridgeUrl("http://localhost:17418/path"), null);
  assert.equal(bridgeUrl("https://127.0.0.1:17418"), null);
  assert.equal(bridgeUrl("http://user:pass@127.0.0.1:17418"), null);
  assert.equal(bridgeUrl("http://example.com:17418"), null);
});

const delay = (ms) => new Promise((r) => setTimeout(r, ms));

test("content script replies before navigation unloads the document", async () => {
  const code = readFileSync(new URL("./content.js", import.meta.url), "utf8");
  for (const action of [{ op: "navigate", url: "http://127.0.0.1:17418/demo" }, { op: "click", text: "Next" }]) {
    let listener = null, unloaded = false;
    const timers = [];
    const el = () => ({ id: "", className: "", textContent: "", isConnected: true, attachShadow: () => ({ append() {} }), setAttribute() {}, addEventListener() {}, append() {}, remove() { this.isConnected = false; } });
    const link = { innerText: "Next", getAttribute: () => "", click() { timers.push(setTimeout(() => { unloaded = true; }, 20)); } };
    const ctx = {
      chrome: { runtime: { onMessage: { addListener(fn) { listener = fn; } }, sendMessage: async () => ({ ok: true }) } },
      document: { body: { innerText: "b" }, title: "T", documentElement: { append() {} }, getElementById: () => null, createElement: el, querySelectorAll: () => [link] },
      window: { getSelection: () => "" }, location: { href: "http://127.0.0.1:17418/demo", assign() { unloaded = true; } },
      URL, Date, Promise, Error, String, clearTimeout,
      setTimeout: (fn, ms) => { const id = setTimeout(fn, ms); timers.push(id); return id; }
    };
    ctx.globalThis = ctx;
    vm.runInNewContext(code, ctx);
    const reply = await new Promise((resolve) => listener({ type: "act", action }, {}, (res) => resolve({ res, unloaded })));
    timers.forEach(clearTimeout);
    assert.deepEqual([reply.unloaded, reply.res.ok], [false, true], `${action.op} replied after unload`);
  }
});

test("background serializes storage updates and revokes session after end-act", async () => {
  let saved = {}, badge = "", onMessage = null, onRemoved = null;
  globalThis.chrome = {
    sidePanel: { setPanelBehavior: async () => {} },
    runtime: { onInstalled: { addListener() {} }, onMessage: { addListener(fn) { onMessage = fn; } } },
    tabs: { onRemoved: { addListener(fn) { onRemoved = fn; } } },
    storage: { session: { async get(k) { await delay(5); return { [k]: structuredClone(saved[k]) }; }, async set(o) { await delay(5); Object.assign(saved, structuredClone(o)); } } },
    action: { setBadgeText: async ({ text }) => { badge = text; }, setBadgeBackgroundColor: async () => {}, setTitle: async () => {} }
  };
  await import(`./background.js?t=${Date.now()}`);
  const send = (m, s = {}) => new Promise((r) => onMessage(m, s, r));
  await send({ type: "grant-tab", tab: { id: 1, url: "http://127.0.0.1:17418/demo", title: "A" } });
  await send({ type: "grant-tab", tab: { id: 2, url: "http://127.0.0.1:17418/demo", title: "B" } });
  onRemoved(1); onRemoved(2);
  await delay(60);
  assert.deepEqual([(await send({ type: "get-state" })).state.grants, badge], [{}, ""]);
  await send({ type: "grant-session" });
  await send({ type: "begin-act", tabId: 3 });
  await Promise.all([send({ type: "revoke-session" }), send({ type: "end-act", tabId: 3 })]);
  assert.equal((await send({ type: "get-state" })).state.session, null);
  await send({ type: "grant-session" });
  await send({ type: "begin-act", tabId: 3 });
  await send({ type: "end-act", tabId: 3 });
  await send({ type: "revoke-acting" }, { tab: { id: 3 } });
  assert.equal((await send({ type: "get-state" })).state.session, null);
});

test("sidepanel binds turns to their tab, navigates via tabs.update, retries site grant, and disconnects", async () => {
  assert.deepEqual(selectPending([{ tabId: 10, turnId: 1 }, { tabId: 10, turnId: 2 }, { tabId: 20, turnId: 1 }], 10), [{ tabId: 10, turnId: 2 }]);
  const mk = (tag = "div") => ({
    tag, className: "", textContent: "", value: "", checked: false, hidden: false, disabled: false,
    children: [], options: [], listeners: {}, parentElement: null, isConnected: true,
    get childElementCount() { return this.children.length; },
    addEventListener(e, fn) { (this.listeners[e] ||= []).push(fn); },
    async emit(e, ev = { preventDefault() {} }) { for (const fn of this.listeners[e] || []) await fn(ev); },
    append(...xs) { for (const x of xs) { x.parentElement = this; this.children.push(x); if (tag === "select") this.options.push(x); } },
    appendChild(x) { this.append(x); return x; },
    replaceChildren() { this.children = []; this.options = []; },
    remove() { this.isConnected = false; if (this.parentElement) this.parentElement.children = this.parentElement.children.filter((c) => c !== this); },
    querySelector(s) { const c = s.startsWith(".") ? s.slice(1) : null; for (const k of this.children) { if ((c && k.className.split(" ").includes(c)) || k.tag === s) return k; const d = k.querySelector(s); if (d) return d; } return null; },
    scrollIntoView() {}
  });
  const ids = Object.fromEntries(["bridge", "token", "include-page", "connect", "app", "disconnect", "status", "acting", "grant-list", "current-tab", "log", "notice", "connect-error", "agent", "text", "send", "connect-form", "composer", "grant-tab", "grant-session"].map((k) => [k, mk(k === "agent" ? "select" : "div")]));
  ids.bridge.value = "http://127.0.0.1:17418"; ids.token.value = "t".repeat(32);
  let state = emptyState(), active = 10, failNextScript = false, gate = null, nextChatBody = null;
  const localStore = { bridge: ids.bridge.value, token: ids.token.value, includePage: false };
  const tabs = new Map([[10, { id: 10, url: "https://a.example/", title: "A" }], [20, { id: 20, url: "https://b.example/", title: "B" }]]);
  const origins = [], actedOn = [], navigated = [], timeouts = [];
  const realSetTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (fn, ms) => { timeouts.push(ms); return realSetTimeout(fn, ms === 700 ? 0 : ms); };
  globalThis.document = { getElementById: (id) => ids[id], createElement: mk };
  globalThis.fetch = async (url) => {
    if (url.endsWith("/health")) return { ok: true, json: async () => ({ status: "ok" }) };
    if (url.endsWith("/agents")) return { ok: true, json: async () => ({ agents: [{ id: "page", name: "Page" }] }) };
    if (gate) { const p = gate; gate = null; await p; }
    return { ok: true, json: async () => nextChatBody };
  };
  globalThis.chrome = {
    storage: { local: { get: async () => ({ ...localStore }), set: async (o) => Object.assign(localStore, o), remove: async (k) => { delete localStore[k]; } }, session: { get: async () => ({ sessionId: "sess-1" }), set: async () => {} }, onChanged: { addListener() {} } },
    tabs: { query: async () => [tabs.get(active)], get: async (id) => { if (!tabs.has(id)) throw new Error("closed"); return tabs.get(id); }, update: async (id, info) => { navigated.push([id, info.url]); return tabs.get(id); }, sendMessage: async (id, m) => { if (m.type === "act") actedOn.push([id, m.action.op]); return { ok: true, detail: `Ran ${m.action?.op || m.type}` }; }, onActivated: { addListener() {} }, onUpdated: { addListener() {} }, onRemoved: { addListener() {} } },
    scripting: { executeScript: async () => { if (failNextScript) { failNextScript = false; throw new Error("no host"); } } },
    permissions: { contains: async () => false, request: async ({ origins: o }) => { origins.push(...o); return true; } },
    runtime: { sendMessage: async (m) => { if (m.type === "get-state") return { ok: true, state }; if (m.type === "grant-tab") { state = grantTab(state, m.tab, 1); return { ok: true, state }; } if (m.type === "grant-session") { state = grantSession(state, 1); return { ok: true, state }; } if (m.type === "begin-act") { const n = beginActing(state, m.tabId, 1); if (!n) return { ok: false }; state = n; return { ok: true, state }; } if (m.type === "end-act") { state = endActing(state, m.tabId); return { ok: true, state }; } return { ok: false }; } }
  };
  try {
    await import(`./sidepanel.js?t=${Date.now()}`);
    await delay(20);
    assert.ok(timeouts.some((ms) => ms >= 120000));
    state = grantTab(state, tabs.get(20), 1);
    nextChatBody = { text: "Clicking", actions: [{ op: "click", text: "Demo", description: "Click Demo" }] };
    let release; gate = new Promise((r) => { release = r; });
    ids.text.value = "click demo";
    const sendPromise = ids.composer.emit("submit");
    await delay(10); active = 20; release(); await sendPromise;
    assert.deepEqual(actedOn, []);
    await ids["grant-session"].emit("click");
    assert.ok(origins.includes("https://b.example/*"));
    assert.deepEqual(actedOn, []);
    await ids.log.querySelector("button").emit("click");
    assert.deepEqual(actedOn, [[10, "click"]]);
    active = 10; nextChatBody = { text: "Open", actions: [{ op: "navigate", url: "https://a.example/next", description: "Open" }] };
    ids.text.value = "open next"; await ids.composer.emit("submit");
    assert.deepEqual(navigated, [[10, "https://a.example/next"]]);
    failNextScript = true; nextChatBody = { text: "Retry", actions: [{ op: "click", text: "Go", description: "Go" }] };
    ids.text.value = "go"; await ids.composer.emit("submit");
    await ids.log.querySelector(".site").emit("click");
    assert.deepEqual(actedOn.at(-1), [10, "click"]);
    await ids.disconnect.emit("click");
    assert.equal(localStore.token, undefined);
  } finally { globalThis.setTimeout = realSetTimeout; }
});
