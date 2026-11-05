// EP2 (#653, spec #648): the plan graph page against its design target
// at 390 and 1440 CSS px, on the
// target's content packet (test/fixtures/plan/target.json): the title row,
// provenance, the blocking chain, each version's state columns and counts,
// folding, Reset, and axe at named states. The screenshots themselves are
// reviewed: with OPENWIZ_PLAN_SHOTS=<dir> this proof writes them there.
// Expected values are the packet's literals, not computed from the page.

import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { after, before, test } from 'node:test';

import { DESKTOP, launchBrowser, openPage, pageIdle, PHONE, waitFor } from '../support/browser.mjs';
import { axe } from '../support/harness.mjs';
import { card, link, openPlan, planSite, sheet, START, tokenColour } from '../fixtures/plan/plan.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(() => browser.close());

const SHOTS = process.env.OPENWIZ_PLAN_SHOTS ?? null;

/** The packet's table: done, building, needs you, waiting; yours. */
const PACKET = [
  ['version:6', '0.0.6 Fleets', ['4 done', '0 building', '1 needs you', '5 waiting'], '3 yours'],
  ['version:8', '0.0.8 PC hub', ['2 done', '1 building', '0 needs you', '7 waiting'], '3 yours'],
  ['version:9', '0.0.9 Loops', ['2 done', '1 building', '0 needs you', '7 waiting'], '2 yours'],
  ['version:10', '0.0.10 Cockpit', ['1 done', '1 building', '0 needs you', '8 waiting'], '2 yours'],
  ['side_spec:2500', 'Side spec #2500 CI speed', ['3 done', '1 building', '1 needs you', '5 waiting'], '2 yours'],
  ['side_spec:2600', 'Side spec #2600 Access', ['2 done', '1 building', '0 needs you', '7 waiting'], '2 yours'],
];
const CHAIN = [2104, 2105, 2107, 2405, 2407, 2408, 2409, 2410];

const counts = (page, key) => sheet(page, key).locator('[data-part=counts] .pl-count').allTextContents();
const visible = (loc) => loc.evaluateAll((els) => els.filter((e) => e.getClientRects().length > 0).length);
const tickets = (page, key, column) => sheet(page, key).locator(`[data-column=${column}] [data-card-ticket]`).evaluateAll((els) => els.map((e) => Number(e.dataset.cardTicket)));

async function noViolations(page, what) {
  assert.deepEqual(await axe(page), [], `no axe violations: ${what}`);
}

for (const [name, viewport] of [['desktop', DESKTOP], ['phone', PHONE]]) {
  test(`EP2: the title row, provenance, chain and every version's counts at ${viewport.width}px`, async () => {
    const fx = await planSite();
    const p = await openPlan(browser, fx, viewport);
    const page = p.page;
    try {
      assert.equal(await page.locator('#pl-title').textContent(), 'Plan');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), viewport.width, 'no sideways scroll');
      const prov = page.locator('[data-part=provenance]');
      assert.equal(await prov.getAttribute('data-state'), 'complete');
      assert.equal(await prov.locator('[data-part=provenance-words]').textContent(), 'Complete · read 09:00:14');
      assert.equal(await page.locator('[data-part=plan-summary]').textContent(), '60 tickets · 4 versions · 2 side specs');
      assert.deepEqual(await page.locator('[data-part=plan] select option').allTextContents(), ['All versions', ...PACKET.map((r) => r[1])]);

      // The chain: root first, its holding count, and the root's needs-you gold.
      assert.equal(await page.locator('#pl-chain-title').textContent(), 'Blocking chain holds 22 tickets');
      assert.deepEqual(await page.locator('[data-chain-ticket]').evaluateAll((els) => els.map((e) => Number(e.dataset.chainTicket))), CHAIN);
      assert.equal(await link(page, 2104).locator('[data-part=holding]').textContent(), 'Holding 22 tickets');
      assert.equal(await link(page, 2104).locator('[data-part=word]').textContent(), 'needs you');
      assert.equal(await link(page, 2409).locator('[data-part=yours]').textContent(), 'yours');

      // Every version keeps its name and every count, folded or not.
      assert.deepEqual(await page.locator('[data-part=version-name]').allTextContents(), PACKET.map((r) => r[1]));
      for (const [key, , words, yours] of PACKET) assert.deepEqual(await counts(page, key), [...words, yours], key);

      // Gold only for what needs Jake: the needs-you mark, never a waiting ticket that is Jake's.
      const gold = await tokenColour(page, '--ow-color-attention');
      if (name === 'phone') await sheet(page, 'version:6').locator('.pl-fold').click();
      assert.equal(await card(page, 2104).locator('.pl-mark').evaluate((el) => getComputedStyle(el).color), gold, 'needs you is gold');
      for (const n of [2109, 2110, 2105]) {
        const colours = await card(page, n).evaluate((el) => [el, ...el.querySelectorAll('*')].flatMap((e) => [getComputedStyle(e).color, getComputedStyle(e).borderTopColor, getComputedStyle(e).backgroundColor]));
        assert.ok(!colours.includes(gold), `#${n} (waiting) has no gold`);
      }
      assert.equal(await card(page, 2109).locator('[data-part=yours]').textContent(), 'yours');
      assert.equal(await card(page, 2109).locator('[data-part=word]').textContent(), 'waiting');
    } finally {
      await p.close();
      await fx.close();
    }
  });
}

test('EP2: the PC opens every version in four state columns, side by side, with "None" for an empty one', async () => {
  const fx = await planSite();
  const p = await openPlan(browser, fx, DESKTOP, { paused: false });
  const page = p.page;
  try {
    for (const [key] of PACKET) assert.equal(await sheet(page, key).locator('.pl-fold').getAttribute('aria-expanded'), 'true', key);
    assert.equal(await visible(page.locator('[data-card-ticket]')), 60, 'all 60 tickets start visible');
    const s = sheet(page, 'version:6');
    assert.deepEqual(await s.locator('.pl-column-title').allTextContents(), ['Done 4', 'Building 0', 'Needs you 1', 'Waiting 5']);
    assert.deepEqual(await tickets(page, 'version:6', 'done'), [2101, 2102, 2103, 2106]);
    assert.deepEqual(await tickets(page, 'version:6', 'needs_you'), [2104]);
    assert.deepEqual(await tickets(page, 'version:6', 'waiting'), [2105, 2107, 2108, 2109, 2110]);
    assert.equal(await s.locator('[data-column=building] .pl-none').textContent(), 'None');
    const xs = await s.locator('.pl-column').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().x));
    assert.ok(xs.every((x, i) => i === 0 || x > xs[i - 1]), `columns side by side: ${xs}`);
    // The chain strip is one row of eight on the PC, above the versions.
    const tops = await page.locator('[data-chain-ticket]').evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
    assert.equal(new Set(tops).size, 1, `one row: ${tops}`);
    assert.equal(await visible(page.locator('[data-chain-ticket]')), 8);
    assert.equal(await page.locator('[data-part=chain-more]').isVisible().catch(() => false), false, 'no "Show more" on the PC');
    const chainBottom = await page.locator('[data-part=chain]').evaluate((e) => e.getBoundingClientRect().bottom);
    assert.ok(chainBottom <= (await sheet(page, 'version:6').evaluate((e) => e.getBoundingClientRect().top)), 'chain on top');
    // Ticket titles at least 14 px, metadata at least 11 px, controls at least 44 px tall.
    assert.equal(await card(page, 2107).locator('[data-part=ticket-title]').evaluate((e) => parseFloat(getComputedStyle(e).fontSize) >= 14), true);
    assert.equal(await card(page, 2107).locator('.pl-num').evaluate((e) => parseFloat(getComputedStyle(e).fontSize) >= 11 && getComputedStyle(e).fontFamily.includes('GeistMono')), true);
    for (const loc of [page.locator('[data-part=plan] select'), page.locator('[data-part=plan-reset]'), sheet(page, 'version:6').locator('.pl-fold'), card(page, 2107)]) {
      assert.ok((await loc.boundingBox()).height >= 44, 'a 44 px target');
    }
    await noViolations(page, 'PC initial');
  } finally {
    await p.close();
    await fx.close();
  }
});

test('EP2: the phone starts with every version folded, four chain links and "Show 4 more links"', async () => {
  const fx = await planSite();
  const p = await openPlan(browser, fx, PHONE, { paused: false });
  const page = p.page;
  try {
    for (const [key] of PACKET) assert.equal(await sheet(page, key).locator('.pl-fold').getAttribute('aria-expanded'), 'false', key);
    assert.equal(await visible(page.locator('[data-card-ticket]')), 0, 'folded: no ticket rows');
    assert.equal(await visible(page.locator('[data-chain-ticket]')), 4);
    const more = page.locator('[data-part=chain-more]');
    assert.equal(await more.textContent(), 'Show 4 more links');
    // The chain is a vertical list on the phone, each link saying what it waits on.
    const tops = await page.locator('[data-chain-ticket]').evaluateAll((els) => els.filter((e) => e.getClientRects().length).map((e) => e.getBoundingClientRect().top));
    assert.ok(tops.every((t, i) => i === 0 || t > tops[i - 1]), 'one under another');
    assert.equal(await page.locator('.pl-arrow-phone').first().evaluate((e) => e.getClientRects().length > 0 && e.textContent), '↑ waits on');
    await noViolations(page, 'phone initial');
    await more.click();
    assert.equal(await visible(page.locator('[data-chain-ticket]')), 8);
    // One version opens as a list grouped by state.
    await sheet(page, 'version:6').locator('.pl-fold').click();
    assert.equal(await visible(sheet(page, 'version:6').locator('[data-card-ticket]')), 10);
    const xs = await sheet(page, 'version:6').locator('.pl-column').evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().x)));
    assert.equal(new Set(xs).size, 1, `groups one under another: ${xs}`);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), PHONE.width, 'no sideways scroll');
    await noViolations(page, 'phone, one version open');
  } finally {
    await p.close();
    await fx.close();
  }
});

for (const [name, viewport] of [['desktop', DESKTOP], ['phone', PHONE]]) {
  test(`EP2: fold keeps the name and every count; Reset opens every version and clears the filter, at ${viewport.width}px`, async () => {
    const fx = await planSite();
    const p = await openPlan(browser, fx, viewport, { paused: false });
    const page = p.page;
    try {
      const fold = sheet(page, 'version:8').locator('.pl-fold');
      await fold.click();
      const open = name === 'phone';
      assert.equal(await fold.getAttribute('aria-expanded'), String(open));
      assert.equal(await visible(sheet(page, 'version:8').locator('[data-card-ticket]')), open ? 10 : 0);
      assert.deepEqual(await counts(page, 'version:8'), ['2 done', '1 building', '0 needs you', '7 waiting', '3 yours']);
      await page.locator('[data-part=plan] select').selectOption({ label: '0.0.9 Loops' });
      assert.deepEqual(await page.locator('[data-part=version-name]').allTextContents(), ['0.0.9 Loops'], 'the filter narrows the lanes');
      assert.equal(await page.locator('[data-chain-ticket]').count(), 8, 'the chain still uses the whole plan');
      await noViolations(page, `${name}, filtered`);
      await page.locator('[data-part=plan-reset]').click();
      assert.equal(await page.locator('[data-part=plan] select').inputValue(), '');
      for (const [key] of PACKET) assert.equal(await sheet(page, key).locator('.pl-fold').getAttribute('aria-expanded'), 'true', `Reset opens ${key}`);
      assert.equal(await visible(page.locator('[data-card-ticket]')), 60);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), viewport.width, 'no sideways scroll');
    } finally {
      await p.close();
      await fx.close();
    }
  });
}

test('EP2: screenshots at 1440 and 390 with the target\'s trace pinned on #2107 (reviewed against the target)', async () => {
  const fx = await planSite();
  try {
    for (const [name, viewport] of [['desktop', DESKTOP], ['phone', PHONE]]) {
      const p = await openPlan(browser, fx, viewport, { paused: false });
      const page = p.page;
      try {
        if (SHOTS) {
          mkdirSync(SHOTS, { recursive: true });
          await page.screenshot({ path: join(SHOTS, `${name}-initial.png`), fullPage: true });
        }
        // The target's state: 0.0.6 open, the others folded, #2107 pinned.
        if (name === 'desktop') for (const [key] of PACKET.slice(1)) await sheet(page, key).locator('.pl-fold').click();
        else await sheet(page, 'version:6').locator('.pl-fold').click();
        await card(page, 2107).click();
        assert.equal(await page.locator('[data-part=trace-counts]').textContent(), '— waits on 2 · 5 wait on it');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), viewport.width, 'no sideways scroll');
        await noViolations(page, `${name}, trace pinned`);
        if (SHOTS) await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
      } finally {
        await p.close();
      }
    }
  } finally {
    await fx.close();
  }
});

test('MD9: the phone bar is Sessions, Fleets, Plan, Decisions, New; the PC sidebar keeps Cockpit, Home and Loops, the command dialog Cockpit and Home; Sessions stays first', async () => {
  const fx = await planSite();
  try {
    for (const viewport of [PHONE, DESKTOP]) {
      const p = await openPage(browser, fx.site.origin, { clock: START, paused: false, stampReads: true, viewport });
      const page = p.page;
      try {
        await waitFor(() => pageIdle(page), { what: 'the first reads consumed' });
        assert.equal(await page.getByRole('heading', { name: 'Sessions', exact: true }).count(), 1, 'Sessions is the initial screen');
        const tabs = await page.locator('.app-nav button').evaluateAll((bs) => bs.filter((b) => b.getClientRects().length > 0).map((b) => b.innerText.trim().replace(/\s+/g, ' ')));
        if (viewport === PHONE) {
          assert.deepEqual(tabs, ['Sessions', 'Fleets', 'Plan', 'Decisions', 'New'], 'MD9, in order: Loops (#549) is never a sixth tab');
          const boxes = await page.locator('.app-nav button').evaluateAll((bs) => bs.filter((b) => b.getClientRects().length > 0).map((b) => { const r = b.getBoundingClientRect(); return [r.width, r.height]; }));
          assert.ok(boxes.every(([w, h]) => w >= 44 && h >= 44), `44 px tabs: ${JSON.stringify(boxes)}`);
        } else {
          assert.deepEqual(tabs, ['Cockpit', 'Home', 'Sessions', 'Fleets', 'Plan', 'Decisions', 'Loops', 'First hour', 'New thread']);
        }
        await page.keyboard.press('Control+k');
        const options = await page.getByRole('option').allTextContents();
        for (const o of ['Go to Home↵', 'Go to Sessions↵', 'Go to Fleets↵', 'Go to Plan↵', 'Go to Cockpit↵']) assert.ok(options.includes(o), `${o} in ${options}`);
        await page.getByRole('combobox', { name: 'Search navigation' }).fill('Go to Plan');
        await page.keyboard.press('Enter');
        await waitFor(async () => (await page.locator('[data-part=plan]').count()) === 1, { what: 'the plan page' });
        assert.equal(await page.getByRole('navigation', { name: 'Views', exact: true }).getByRole('button', { name: 'Plan', exact: true }).getAttribute('aria-pressed'), 'true');
      } finally {
        await p.close();
      }
    }
  } finally {
    await fx.close();
  }
});

test('#549 entry: the Plan screen links to Loops at 390 and 1440 when the shell has a Loops screen, and draws no dead link before it does', async () => {
  const fx = await planSite();
  try {
    for (const viewport of [PHONE, DESKTOP]) {
      const p = await openPlan(browser, fx, viewport, { paused: false });
      const page = p.page;
      try {
        // The phone hides Loops from its bar (MD9), so find the shell's Loops by its class, not its role.
        const shellHasLoops = (await page.locator('.app-nav .nav-loops').count()) > 0;
        const link = page.locator('[data-part=plan-loops]');
        if (!shellHasLoops) {
          // Until #549 wires its showLoops into the Plan mount, there is nowhere to go.
          assert.equal(await link.count(), 0, 'no Loops link without a Loops screen');
          continue;
        }
        assert.equal(await link.textContent(), 'Loops');
        assert.ok((await link.boundingBox()).height >= 44);
        await link.click();
        await waitFor(async () => (await page.locator('.app-nav .nav-loops').getAttribute('aria-pressed')) === 'true', { what: 'the Loops screen' });
        assert.equal(await page.locator('[data-part=plan]').count(), 0, 'the Plan screen gave way to Loops');
        await waitFor(async () => (await page.locator('[data-part=loops]').count()) === 1, { what: 'the Loops page' });
        if (viewport === PHONE) {
          const tabs = await page.locator('.app-nav button').evaluateAll((bs) => bs.filter((b) => b.getClientRects().length > 0).map((b) => b.innerText.trim()));
          assert.ok(!tabs.includes('Loops') && tabs.length <= 5, `Loops is never a phone tab: ${tabs}`);
        }
      } finally {
        await p.close();
      }
    }
  } finally {
    await fx.close();
  }
});
