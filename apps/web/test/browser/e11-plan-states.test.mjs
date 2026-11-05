// EP2 (#653): the plan page's honest states, from the target's README: loading,
// partial (dashed, never gold, gaps said), stale (with the read time, aging on
// this clock), a failed read with and without a last snapshot, empty only when
// complete and fresh, the chain null, unknown, of one and long, an unknown
// column, unknown ownership, prerequisites outside the plan, a lane with no
// tickets, and a response the strict reader refuses. Synthetic literals only.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, PHONE, waitFor } from '../support/browser.mjs';
import { apiError, json } from '../support/fake-api.mjs';
import { axe } from '../support/harness.mjs';
import { aged, card, emptyPlan, finished, link, openPlan, planSite, row, sheet, target, ticket, tokenColour, withGraph, withLine } from '../fixtures/plan/plan.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

async function withPlan(doc, viewport, fn, opts) {
  const fx = await planSite(doc);
  const p = await openPlan(browser, fx, viewport, opts);
  try {
    await fn(p.page, fx, p);
  } finally {
    await p.close();
    await fx.close();
  }
}
const words = (page) => page.locator('[data-part=provenance-words]').textContent();
const state = (page) => page.locator('[data-part=provenance]').getAttribute('data-state');

test('EP2: loading shows a quiet skeleton and no counts until the first read', async () => {
  const fx = await planSite();
  fx.holding = true;
  const p = await openPlan(browser, fx, DESKTOP, { wait: false });
  try {
    await waitFor(() => fx.held.length === 1, { what: 'the held read' });
    assert.equal(await p.page.locator('[data-part=plan-loading]').isVisible(), true);
    assert.equal(await p.page.locator('[data-part=counts], [data-chain-ticket], [data-part=provenance]').count(), 0, 'no fake counts');
    fx.releaseReads();
    await waitFor(async () => (await p.page.locator('[data-part=provenance]').count()) === 1, { what: 'the plan' });
  } finally {
    await p.close();
    await fx.close();
  }
});

for (const viewport of [DESKTOP, PHONE]) {
  test(`EP2: partial coverage is dashed, never gold, says its gaps and keeps every usable lane, at ${viewport.width}px`, async () => {
    const doc = target();
    doc.coverage = { state: 'partial', gaps: [{ kind: 'timed_out', detail: 'Synthetic milestone page 2 timed out' }, { kind: 'not_found', detail: 'Synthetic parent of #2999 not found' }] };
    await withPlan(doc, viewport, async (page) => {
      assert.equal(await state(page), 'partial');
      assert.equal(await words(page), 'Partial · read 09:00:14 · 2 gaps');
      assert.equal(await page.locator('[data-part=gap-summary]').textContent(), 'Synthetic milestone page 2 timed out · Synthetic parent of #2999 not found');
      const chip = page.locator('[data-part=provenance] .status-chip');
      assert.equal(await chip.evaluate((e) => getComputedStyle(e).borderTopStyle), 'dashed');
      assert.notEqual(await chip.evaluate((e) => getComputedStyle(e).color), await tokenColour(page, '--ow-color-attention'), 'never gold');
      assert.equal(await page.locator('[data-part=version]').count(), 6, 'usable lanes stay');
      assert.equal(await page.getByText(/all clear|nothing is blocking|no plan yet/i).count(), 0);
      await page.locator('[data-part=provenance] button').click();
      assert.deepEqual(await page.locator('[data-part=gaps] li').allTextContents(), ['timed_out · Synthetic milestone page 2 timed out', 'not_found · Synthetic parent of #2999 not found']);
      assert.deepEqual(await axe(page), [], 'no axe violations: partial, gaps open');
    }, { paused: false });
  });
}

for (const viewport of [DESKTOP, PHONE]) {
  test(`EP2: stale says "Stale · read HH:MM:SS" and keeps the data; a fresh read turns stale on this clock; stale and partial says both, dashed, at ${viewport.width}px`, async () => {
    await withPlan(aged(target(), 80_000), viewport, async (page) => {
      assert.equal(await state(page), 'stale');
      assert.equal(await words(page), 'Stale · read 08:58:55');
      assert.equal(await page.locator('[data-card-ticket]').count(), 60, 'the data stays');
    });
    await withPlan(target(), viewport, async (page, fx) => {
      assert.equal(await state(page), 'complete');
      fx.holding = true; // the next read never answers: only this clock moves
      await page.clock.runFor(70_000);
      await waitFor(async () => (await state(page)) === 'stale', { what: 'aged past 70 s' });
      assert.equal(await words(page), 'Stale · read 09:00:14');
    });
    const both = aged(target(), 80_000);
    both.coverage = { state: 'partial', gaps: [{ kind: 'timed_out', detail: 'Synthetic milestone page 2 timed out' }] };
    await withPlan(both, viewport, async (page) => {
      assert.equal(await words(page), 'Stale · Partial · read 08:58:55 · 1 gap', 'coverage and freshness are independent');
      assert.equal(await page.locator('[data-part=provenance] .status-chip').evaluate((e) => getComputedStyle(e).borderTopStyle), 'dashed');
    });
    const unknown = target();
    unknown.freshness = { state: 'unknown', snapshot_at: { unknown: 'source time not reported' } };
    await withPlan(unknown, viewport, async (page) => {
      assert.equal(await words(page), 'Freshness unknown · read time unknown (source time not reported)');
      assert.equal(await page.locator('.connection-footer .conn').getAttribute('data-connection'), 'stale', 'unknown freshness is never live');
    });
  });
}

test('EP2: a failed read keeps the last snapshot with its time and the reason, and Retry reads again; with nothing yet, the error panel', async () => {
  const fx = await planSite();
  const p = await openPlan(browser, fx, DESKTOP);
  const page = p.page;
  try {
    fx.reply = apiError(500, 'internal', 'Synthetic plan read failed');
    const reads = fx.reads;
    await page.clock.runFor(61_000);
    await waitFor(async () => (await page.locator('[data-part=plan] [data-notice]').count()) === 1, { what: 'the failure' });
    const notice = page.locator('[data-part=plan] [data-notice]');
    assert.equal(await notice.locator('.notice-body').textContent(), 'internal: Synthetic plan read failed');
    assert.equal(await notice.locator('.meta').textContent(), 'last good snapshot 09:00:14');
    assert.equal(await page.locator('[data-card-ticket]').count(), 60, 'the last snapshot stays');
    fx.reply = null;
    const before = fx.reads;
    assert.ok(before > reads);
    await notice.getByRole('button', { name: 'Retry' }).click();
    await waitFor(async () => (await page.locator('[data-part=plan] [data-notice]').count()) === 0, { what: 'the retried read' });
    assert.ok(fx.reads > before);
  } finally {
    await p.close();
    await fx.close();
  }
  const empty = await planSite();
  empty.reply = json(200, { schema: 'openwiz.plan.v1' });
  const q = await openPlan(browser, empty, PHONE, { paused: false });
  try {
    const notice = q.page.locator('[data-part=plan] [data-notice]');
    assert.equal(await notice.getAttribute('data-notice'), 'error');
    assert.match(await notice.getAttribute('class'), /session-state/, 'the Sessions-style error panel');
    assert.equal(await notice.locator('.meta').textContent(), 'no snapshot yet');
    assert.equal(await q.page.locator('[data-part=counts]').count(), 0);
    assert.deepEqual(await axe(q.page), [], 'no axe violations: read failed, nothing yet');
  } finally {
    await q.close();
    await empty.close();
  }
});

test('EP2: the strict reader refuses a key written twice, an integer written 1.0, another repository, a one-sided edge, contradictory facts, a future source time and a missing prerequisite in a complete read', async () => {
  const text = JSON.stringify(target());
  const bad = [
    text.replace('"schema": "openwiz.plan.v1"', '"schema": "openwiz.plan.v1", "schema": "openwiz.plan.v1"').replace('"schema":"openwiz.plan.v1"', '"schema":"openwiz.plan.v1","schema":"openwiz.plan.v1"'),
    text.replace('"number":2101', '"number":2101.0'),
    JSON.stringify((() => { const d = target(); ticket(d, 2101).url.known = 'https://github.com/other-owner/example-plan/issues/2101'; return d; })()),
    JSON.stringify((() => { const d = target(); ticket(d, 2101).dependents.known = []; return d; })()),
    // A contradiction between facts: done without a merge, ownership against labels, one spec in two lanes.
    JSON.stringify((() => { const d = target(); ticket(d, 2105).column = { known: 'done' }; return d; })()),
    JSON.stringify((() => { const d = target(); ticket(d, 2105).yours = { known: true }; return d; })()),
    JSON.stringify((() => { const d = target(); ticket(d, 2105).lane = { known: { kind: 'version', number: 8 } }; return d; })()),
    // Ownership is not actionability: ready-for-human alone never makes "needs you" (column rules 3-5, R3).
    JSON.stringify((() => { const d = target(); Object.assign(ticket(d, 2107), { column: { known: 'needs_you' }, labels: { known: ['ready-for-human'] }, yours: { known: true } }); return d; })()),
    JSON.stringify((() => { const d = target(); Object.assign(ticket(d, 2202), { column: { known: 'needs_you' }, labels: { known: ['ready-for-human'] }, yours: { known: true } }); return d; })()),
    // A hold label cannot place a ticket before its merge status is known (rule 1 first).
    JSON.stringify((() => { const d = target(); Object.assign(ticket(d, 2105), { state: { unknown: 'state read failed' }, pr: { unknown: 'pull request read failed' }, labels: { known: ['held', 'ready-for-agent'] }, column: { known: 'needs_you' } }); return d; })()),
    // Unread labels with ownership said either way (R4).
    JSON.stringify((() => { const d = target(); Object.assign(ticket(d, 2105), { labels: { unknown: 'label read failed' }, yours: { known: true }, column: { unknown: 'label read failed' } }); return d; })()),
    JSON.stringify((() => { const d = target(); Object.assign(ticket(d, 2105), { labels: { unknown: 'label read failed' }, yours: { known: false }, column: { unknown: 'label read failed' } }); return d; })()),
    // A source time after assembly.
    JSON.stringify((() => { const d = target(); d.freshness.snapshot_at.known = d.snapshot_at + 1; return d; })()),
    // A prerequisite that is not listed, in a read that claims to be complete.
    JSON.stringify((() => { const d = target(); ticket(d, 2101).blockers.known = [2001]; return d; })()),
  ];
  for (const [i, body] of bad.entries()) {
    assert.notEqual(body, text, `case ${i} changes the text`);
    const fx = await planSite();
    fx.reply = { ...json(200, {}), body };
    const p = await openPlan(browser, fx, DESKTOP);
    try {
      assert.equal(await p.page.locator('[data-part=plan] [data-notice]').getAttribute('data-notice'), 'error', `case ${i} refused`);
      assert.equal(await p.page.locator('[data-card-ticket]').count(), 0);
    } finally {
      await p.close();
      await fx.close();
    }
  }
});

for (const viewport of [DESKTOP, PHONE]) {
  test(`EP2: empty says "No plan yet" only when complete and fresh, and its limit otherwise, at ${viewport.width}px`, async () => {
    await withPlan(emptyPlan(), viewport, async (page) => {
      assert.equal(await page.locator('[data-part=plan-empty]').textContent(), 'No plan yet');
      assert.equal(await page.locator('[data-part=plan-summary]').textContent(), '0 tickets · 0 versions · 0 side specs');
    });
    const partial = emptyPlan();
    partial.coverage = { state: 'partial', gaps: [{ kind: 'command_failed', detail: 'Synthetic milestones unread' }] };
    await withPlan(partial, viewport, async (page) => {
      assert.equal(await page.locator('[data-part=plan-empty]').textContent(), 'No tickets read: this read is partial, so the plan may not be empty');
    });
    await withPlan(aged(emptyPlan(), 90_000), viewport, async (page) => {
      assert.equal(await page.locator('[data-part=plan-empty]').textContent(), 'No tickets read: this read is stale');
    });
  });
}

for (const viewport of [DESKTOP, PHONE]) {
  test(`EP2: a finished plan says "Nothing is blocking"; an unknown chain says why and shows no partial maximum; a chain that does not fit the plan is unknown, at ${viewport.width}px`, async () => {
    await withPlan(finished(), viewport, async (page) => {
      assert.equal(await page.locator('[data-part=chain-none]').textContent(), 'Nothing is blocking');
      assert.equal(await page.locator('[data-chain-ticket]').count(), 0);
    });
    const unknown = target();
    unknown.critical_chain = { unknown: 'a dependency cycle (malformed)' };
    await withPlan(unknown, viewport, async (page) => {
      assert.equal(await page.locator('[data-part=chain-unknown]').textContent(), 'Blocking chain unknown: a dependency cycle (malformed)');
      assert.equal(await page.locator('[data-chain-ticket]').count(), 0);
    });
    // Named through a merged ticket, along no real edge, with an impossible count.
    const made = target();
    made.critical_chain = { known: { root: 2101, blocked_count: 999, path: [2101, 2601] } };
    await withPlan(made, viewport, async (page) => {
      assert.equal(await page.locator('[data-part=chain-unknown]').textContent(), 'Blocking chain unknown: the named chain is not this plan\'s largest blocking chain');
    });
    const none = target();
    none.critical_chain = { known: null };
    await withPlan(none, viewport, async (page) => {
      assert.equal(await page.locator('[data-part=chain-unknown]').textContent(), 'Blocking chain unknown: the plan has unfinished tickets but named no chain');
      assert.equal(await page.locator('[data-part=chain-none]').count(), 0, 'never "Nothing is blocking" while tickets are unfinished');
    });
  });
}

test('EP2: labels in the server\'s Unicode scalar order are read (R1: past U+FFFF, UTF-16 order differs)', async () => {
  const doc = target();
  ticket(doc, 2101).labels = { known: ['ready-for-agent', 'Ａ', '🚀'] };
  await withPlan(doc, DESKTOP, async (page) => {
    assert.equal(await page.locator('[data-part=plan] [data-notice]').count(), 0);
    assert.equal(await page.locator('[data-card-ticket]').count(), 60);
  });
  const wrong = target();
  ticket(wrong, 2101).labels = { known: ['ready-for-agent', '🚀', 'Ａ'] };
  await withPlan(wrong, DESKTOP, async (page) => {
    assert.equal(await page.locator('[data-part=plan] [data-notice]').getAttribute('data-notice'), 'error', 'out of scalar order is refused');
  });
});

test('EP2: a named chain is kept only when it is the plan\'s own: largest reach, then the longest path, then the smallest root and path; never through a cycle', async () => {
  const shown = async (doc) => {
    let out = null;
    await withPlan(doc, DESKTOP, async (page) => {
      out = (await page.locator('[data-part=chain-unknown]').count()) > 0
        ? await page.locator('[data-part=chain-unknown]').textContent()
        : await page.locator('[data-chain-ticket]').evaluateAll((els) => els.map((e) => Number(e.dataset.chainTicket)));
    });
    return out;
  };
  const NOT = 'Blocking chain unknown: the named chain is not this plan\'s largest blocking chain';
  const named = (doc, root, count, path) => { doc.critical_chain = { known: { root, blocked_count: count, path } }; return doc; };
  // The target's own chain, shortened, or rooted elsewhere (#2202 reaches 13; #2104 reaches 22).
  assert.equal(await shown(named(target(), 2104, 22, [2104])), NOT, 'not a longest path');
  assert.equal(await shown(named(target(), 2202, 13, [2202, 2204, 2206, 2207, 2208, 2210])), NOT, 'not the largest reach');
  // The target's own root and path with a wrong count (#2104 reaches 22, not 21).
  assert.equal(await shown(named(target(), 2104, 21, [2104, 2105, 2107, 2405, 2407, 2408, 2409, 2410])), NOT, 'the count is checked on its own');
  // Merged is merged, whatever the display column says: a verified merge never blocks (R2).
  const merged = () => {
    const d = target();
    const t = ticket(d, 2101);
    Object.assign(t, { column: { unknown: 'column derivation unavailable' }, blockers: { known: [] }, dependents: { known: [] } });
    d.tickets = [t];
    d.coverage = { state: 'partial', gaps: [{ kind: 'missing_field', detail: 'Synthetic column derivation unavailable' }] };
    return d;
  };
  assert.equal(await shown(named(merged(), 2101, 0, [2101])), 'Blocking chain unknown: a chain was named in a plan with nothing unfinished', 'a merged ticket is never a blocking root');
  await withPlan(Object.assign(merged(), { critical_chain: { known: null } }), DESKTOP, async (page) => {
    assert.equal(await page.locator('[data-part=chain-none]').textContent(), 'Nothing is blocking', 'its correct null chain is kept');
  });
  // Equal reach and length: the smaller root wins.
  const twins = [[2701, []], [2702, [2701]], [2711, []], [2712, [2711]]];
  assert.deepEqual(await shown(named(withGraph(twins), 2701, 1, [2701, 2702])), [2701, 2702]);
  assert.equal(await shown(named(withGraph(twins), 2711, 1, [2711, 2712])), NOT, 'a tie goes to the smaller root');
  // Equal reach: the longer onward path wins.
  const longer = [[2701, []], [2702, [2701]], [2703, [2701]], [2711, []], [2712, [2711]], [2713, [2712]]];
  assert.deepEqual(await shown(named(withGraph(longer), 2711, 2, [2711, 2712, 2713])), [2711, 2712, 2713]);
  assert.equal(await shown(named(withGraph(longer), 2701, 2, [2701, 2702])), NOT, 'a tie on reach goes to the longer path');
  // Two equally long onward paths: the numerically smaller one.
  const fork = [[2701, []], [2702, [2701]], [2703, [2701]]];
  assert.deepEqual(await shown(named(withGraph(fork), 2701, 2, [2701, 2702])), [2701, 2702]);
  assert.equal(await shown(named(withGraph(fork), 2701, 2, [2701, 2703])), NOT, 'the smaller path on a tie');
  // A cycle anywhere, even apart from the chain: no chain.
  assert.equal(await shown(withGraph([[2701, [2702]], [2702, [2701]]], target())), 'Blocking chain unknown: the plan\'s prerequisites form a cycle');
  // A cycle is also a malformed gap: the read is partial, and says so.
  await withPlan(withGraph([[2701, [2702]], [2702, [2701]]], target()), DESKTOP, async (page) => {
    assert.equal(await page.locator('[data-part=provenance-words]').textContent(), 'Partial · read 09:00:14 · 1 gap');
    assert.equal(await page.locator('[data-part=gap-summary]').textContent(), 'the plan\'s prerequisites form a cycle');
  });
});

test('EP2: a chain of one; a long chain scrolls inside its panel on the PC and shows 4 + "Show 8 more links" on the phone', async () => {
  await withPlan(withLine(1), DESKTOP, async (page) => {
    assert.equal(await page.locator('#pl-chain-title').textContent(), 'Blocking chain holds 0 tickets');
    assert.equal(await page.locator('[data-chain-ticket]').count(), 1);
    assert.equal(await link(page, 2701).locator('[data-part=holding]').textContent(), 'Holding 0 tickets');
  });
  await withPlan(withLine(1), PHONE, async (page) => {
    assert.equal(await page.locator('[data-chain-ticket]').count(), 1);
    assert.equal(await page.locator('[data-part=chain-more]').count(), 0);
  });
  await withPlan(withLine(12), DESKTOP, async (page) => {
    assert.equal(await page.locator('#pl-chain-title').textContent(), 'Blocking chain holds 11 tickets');
    assert.equal(await page.locator('[data-chain-ticket]').count(), 12);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), DESKTOP.width, 'no page overflow');
    const strip = page.locator('.pl-chain-list');
    assert.ok(await strip.evaluate((e) => e.scrollWidth > e.clientWidth && getComputedStyle(e).overflowX === 'auto'), 'the strip scrolls');
  });
  await withPlan(withLine(12), PHONE, async (page) => {
    assert.equal(await page.locator('[data-part=chain-more]').textContent(), 'Show 8 more links');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), PHONE.width, 'no sideways scroll');
  });
});

test('EP2: a partial read keeps rows that name an unread prerequisite, says it is not read, and claims no chain; unread prerequisite lists make dependents unknown', async () => {
  const doc = target();
  doc.coverage = { state: 'partial', gaps: [{ kind: 'not_found', detail: 'Synthetic prerequisite #2001 could not be read' }] };
  doc.critical_chain = { unknown: 'a referenced prerequisite was not read' };
  ticket(doc, 2101).blockers = { known: [2001] };
  await withPlan(doc, DESKTOP, async (page) => {
    assert.equal(await page.locator('[data-card-ticket]').count(), 60, 'every usable row stays');
    await card(page, 2101).click();
    assert.deepEqual(await page.locator('[data-part=trace] ul').nth(0).locator('li').allTextContents(), ['#2001 not read']);
    assert.equal(await page.locator('[data-part=trace-counts]').textContent(), '— waits on 1 · 2 wait on it');
  });
  const unread = target();
  ticket(unread, 2108).blockers = { unknown: 'synthetic: blocked-by list unread' };
  unread.coverage = { state: 'partial', gaps: [{ kind: 'command_failed', detail: 'Synthetic blocked-by read failed' }] };
  await withPlan(unread, DESKTOP, async (page) => {
    await card(page, 2107).click();
    assert.equal(await page.locator('[data-part=trace-counts]').textContent(), '— waits on 2 · what waits on it is unknown', 'no confident dependents while a prerequisite list is unread');
    assert.equal(await page.locator('[data-part=chain-unknown]').textContent(), 'Blocking chain unknown: a prerequisite list in this plan was not read');
  });
});

test('EP2: twenty tickets in one column stay in that column, at 1440 and 390', async () => {
  const d = target();
  const lane = { kind: 'side_spec', number: 2800 };
  d.lanes.push({ ...lane, title: { known: 'Wide column' } });
  for (let i = 1; i <= 20; i++) d.tickets.push(row(2800 + i, `Wide ${i}`, lane));
  for (const viewport of [DESKTOP, PHONE]) {
    await withPlan(d, viewport, async (page) => {
      const s = sheet(page, 'side_spec:2800');
      if (viewport === PHONE) await s.locator('.pl-fold').click();
      assert.deepEqual(await s.locator('.pl-column-title').allTextContents(), ['Done 0', 'Building 0', 'Needs you 0', 'Waiting 20']);
      assert.equal(await s.locator('[data-column=waiting] [data-card-ticket]').count(), 20);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), viewport.width, 'no sideways scroll');
    });
  }
});

test('EP2: an unknown column gets a fifth column with its reason; unknown ownership says so; outside prerequisites are listed apart; an empty lane says "No tickets"; long titles stay readable', async () => {
  const doc = target();
  const t = ticket(doc, 2108);
  t.column = { unknown: 'closed without a verified merge' };
  t.state = { unknown: 'closed without a verified merge' };
  // Unread labels: ownership unknown, and the column too (its rules need them).
  ticket(doc, 2110).yours = { unknown: 'labels unread' };
  ticket(doc, 2110).labels = { unknown: 'labels unread' };
  ticket(doc, 2110).column = { unknown: 'labels unread' };
  ticket(doc, 2105).title = { known: 'A synthetic ticket title long enough to wrap onto more than two lines in a narrow state column so that it must end in an ellipsis' };
  // An unparented prerequisite of #2101, outside every lane.
  ticket(doc, 2101).blockers = { known: [2050] };
  doc.tickets.unshift({ number: 2050, title: { known: 'Outside prerequisite' }, url: { known: 'https://github.com/example-owner/example-plan/issues/2050' }, spec: { known: null }, lane: { known: null }, state: { known: 'merged' }, column: { known: 'done' }, labels: { known: [] }, yours: { known: false }, blockers: { known: [] }, dependents: { known: [2101] }, pr: { known: null } });
  // A version with no tickets.
  doc.lanes.splice(4, 0, { kind: 'version', number: 11, title: { known: '0.0.11 Decide' } });
  await withPlan(doc, DESKTOP, async (page) => {
    const s = sheet(page, 'version:6');
    assert.deepEqual(await s.locator('.pl-column-title').allTextContents(), ['Done 4', 'Building 0', 'Needs you 1', 'Waiting 3', 'Unknown 2']);
    assert.equal(await card(page, 2108).locator('[data-part=word]').textContent(), 'unknown (closed without a verified merge)');
    assert.deepEqual(await s.locator('[data-part=counts] .pl-count').allTextContents(), ['4 done', '0 building', '1 needs you', '3 waiting', '2 unknown', '2 yours · 1 owner unknown']);
    assert.equal(await card(page, 2110).locator('[data-part=yours]').textContent(), 'owner unknown');
    assert.equal(await sheet(page, 'version:8').locator('[data-column=unknown]').count(), 0, 'no fifth column where none is unknown');
    assert.equal(await sheet(page, 'version:11').locator('[data-part=no-tickets]').textContent(), 'No tickets');
    const outside = sheet(page, 'outside');
    assert.equal(await outside.locator('[data-part=version-name]').textContent(), 'Outside this plan');
    assert.equal(await outside.locator('[data-card-ticket]').count(), 1);
    assert.deepEqual(await page.locator('[data-part=version-name]').allTextContents(), ['0.0.6 Fleets', '0.0.8 PC hub', '0.0.9 Loops', '0.0.10 Cockpit', '0.0.11 Decide', 'Side spec #2500 CI speed', 'Side spec #2600 Access', 'Outside this plan']);
    // The outside prerequisite traces like any other ticket.
    await card(page, 2101).click();
    assert.equal(await page.locator('[data-part=trace] ul').nth(0).locator('li').allTextContents().then((x) => x.join()), '#2050 Outside prerequisite · Outside this plan');
    // A long title: at most two lines, the full title in its accessible name, 14 px.
    const title = card(page, 2105).locator('[data-part=ticket-title]');
    const lines = await title.evaluate((e) => Math.round(e.getBoundingClientRect().height / parseFloat(getComputedStyle(e).lineHeight)));
    assert.ok(lines <= 2, `${lines} lines`);
    assert.match(await card(page, 2105).evaluate((e) => e.textContent), /must end in an ellipsis/);
    assert.deepEqual(await axe(page), [], 'no axe violations: unknowns, outside and empty lane');
  }, { paused: false });
});
