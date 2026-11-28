export function emptyState() {
  return { grants: {}, session: null, acting: null };
}

export function tabGrantable(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export function bridgeUrl(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:") return null;
  if (parsed.hostname !== "127.0.0.1" && parsed.hostname !== "localhost") return null;
  if (parsed.username || parsed.password) return null;
  if (parsed.pathname !== "/" && parsed.pathname !== "") return null;
  if (parsed.search || parsed.hash) return null;
  const port = parsed.port === "" ? 80 : Number(parsed.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
  return `http://${parsed.hostname}:${port}`;
}

function clean(value, max) {
  if (value == null) return "";
  return String(value).replace(/\0/g, "").slice(0, max);
}

function httpUrl(value) {
  try {
    const parsed = new URL(value);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && parsed.hostname ? parsed.href : "";
  } catch {
    return "";
  }
}

export function acceptAction(raw) {
  if (!raw || typeof raw !== "object") return null;
  const op = raw.op;
  if (op !== "read" && op !== "click" && op !== "type" && op !== "navigate") return null;
  const action = {
    id: clean(raw.id, 64),
    op,
    description: clean(raw.description, 200),
    selector: clean(raw.selector, 300),
    text: clean(raw.text, 200),
    url: clean(raw.url, 2048),
    value: clean(raw.value, 2000)
  };
  if (action.selector && /[\n\r<>]/.test(action.selector)) return null;
  if (op === "navigate") {
    const href = httpUrl(action.url);
    if (!href) return null;
    action.url = href;
  }
  if (op === "click" && !action.selector && !action.text) return null;
  if (op === "type" && !action.value) return null;
  if (op === "read" && (action.url || action.value)) return null;
  return action;
}

export function grantTab(state, tab, now) {
  if (!tab || tab.id == null || !tabGrantable(tab.url)) return null;
  const origin = new URL(tab.url).origin;
  return {
    grants: {
      ...state.grants,
      [String(tab.id)]: {
        scope: "tab",
        origin,
        url: tab.url,
        title: clean(tab.title, 120),
        at: now
      }
    },
    session: state.session,
    acting: state.acting
  };
}

export function grantSession(state, now) {
  return { grants: { ...state.grants }, session: { at: now }, acting: state.acting };
}

export function revokeTab(state, tabId) {
  const grants = { ...state.grants };
  delete grants[String(tabId)];
  const acting = state.acting && String(state.acting.tabId) === String(tabId) ? null : state.acting;
  return { grants, session: state.session, acting };
}

export function revokeSession(state) {
  const acting = state.acting && state.acting.via === "session" ? null : state.acting;
  return { grants: { ...state.grants }, session: null, acting };
}

export function canAct(state, tabId) {
  if (!state) return null;
  if (state.grants && state.grants[String(tabId)]) return "tab";
  if (state.session) return "session";
  return null;
}

export function beginActing(state, tabId, now) {
  const via = canAct(state, tabId);
  if (!via || tabId == null || !Number.isFinite(Number(tabId))) return null;
  return {
    grants: state.grants,
    session: state.session,
    acting: { tabId: Number(tabId), via, at: now }
  };
}

export function endActing(state, tabId) {
  if (!state.acting || String(state.acting.tabId) !== String(tabId)) return state;
  return { grants: state.grants, session: state.session, acting: null };
}

export function badgeText(state) {
  if (state && state.acting) return "ACT";
  if (state && (state.session || Object.keys(state.grants || {}).length)) return "ON";
  return "";
}

export function revokeActing(state, tabId) {
  const via = state.acting && String(state.acting.tabId) === String(tabId)
    ? state.acting.via
    : canAct(state, tabId);
  const next = via === "session" ? revokeSession(state) : revokeTab(state, tabId);
  return endActing(next, tabId);
}

export function createQueue() {
  let tail = Promise.resolve();
  return (task) => {
    const run = tail.then(task, task);
    tail = run.then(() => undefined, () => undefined);
    return run;
  };
}

export function selectPending(items, tabId) {
  let latestTurn = null;
  for (const item of items) {
    if (String(item.tabId) === String(tabId) && (latestTurn == null || item.turnId > latestTurn)) {
      latestTurn = item.turnId;
    }
  }
  if (latestTurn == null) return [];
  return items.filter((item) => String(item.tabId) === String(tabId) && item.turnId === latestTurn);
}
