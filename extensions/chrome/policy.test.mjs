import assert from "node:assert/strict";
import test from "node:test";
import {
  acceptAction,
  badgeText,
  beginActing,
  bridgeUrl,
  canAct,
  emptyState,
  endActing,
  grantSession,
  grantTab,
  revokeSession,
  revokeTab,
  tabGrantable
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
