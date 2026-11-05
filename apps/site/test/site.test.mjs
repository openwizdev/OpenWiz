import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { after, before, test } from 'node:test';
import { landing, changelog, landingLinks, changelogLinks, setupPrompt, costLine, cloudroomHref, notOffered, bannedLanding, landingCharsBefore1190, stage, stageLabel } from './approved-copy.mjs';

// Reuse the repository's approved test tools; the site adds no dependency.
const require = createRequire(new URL('../../web/package.json', import.meta.url));
const { chromium } = require('playwright-core');
const axe = require.resolve('axe-core/axe.min.js');
const files = new Map([
  ['/', ['index.html', 'text/html']], ['/changelog', ['changelog/index.html', 'text/html']],
  ['/changelog/', ['changelog/index.html', 'text/html']], ['/style.css', ['style.css', 'text/css']],
  ['/script.js', ['script.js', 'text/javascript']], ['/tokens.css', ['tokens.css', 'text/css']],
  ['/fonts/Geist-var.woff2', ['fonts/Geist-var.woff2', 'font/woff2']],
  ['/fonts/GeistMono-var.woff2', ['fonts/GeistMono-var.woff2', 'font/woff2']],
  ['/fonts/Virgil.woff2', ['fonts/Virgil.woff2', 'font/woff2']],
]);
let server, browser, origin;
before(async () => {
  server = createServer(async (req, res) => {
    const file = files.get(new URL(req.url, 'http://localhost').pathname);
    if (!file) { res.writeHead(404).end(); return; }
    try {
      const data = await readFile(new URL(`../dist/${file[0]}`, import.meta.url));
      res.writeHead(200, { 'Content-Type': file[1] }).end(data);
    } catch { res.writeHead(500).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ executablePath: process.env.OPENWIZ_CHROMIUM ?? '/usr/bin/chromium' });
});
after(async () => {
  await browser?.close();
  await new Promise(resolve => server?.close(resolve));
});
const normalize = text => text.replace(/\s+/g, ' ').trim();
// #1352: the landing's intro is one labelled illustration (role="img"); the page's claims are
// main without it, and the illustration holds only its approved synthetic text and label.
const claims = main => {
  const stage = main.querySelector('.intro');
  if (stage) stage.hidden = true;
  const text = { inner: main.innerText, all: main.textContent.replace(stage?.textContent ?? '', '') };
  if (stage) stage.hidden = false;
  return text;
};
async function checkCopy(page, route) {
  const text = await page.locator('main').evaluate(claims);
  assert.equal(normalize(text.inner), route === '/' ? landing : changelog, 'approved claim regions');
  assert.equal(text.all.replace(/\s/g, ''), (route === '/' ? landing : changelog).replace(/\s/g, ''), 'no extra hidden claim text');
  assert.deepEqual(await page.locator('main a').evaluateAll(links => links.map(a => a.getAttribute('href'))), route === '/' ? landingLinks : changelogLinks, 'approved evidence and action links');
  if (route === '/') {
    assert.equal(normalize(await page.locator('main .intro').textContent()), stage, 'the illustration holds only its synthetic text');
    assert.equal(await page.locator('main .intro').getAttribute('role'), 'img');
    assert.equal(await page.locator('main .intro').getAttribute('aria-label'), stageLabel, 'the illustration says it is not released');
    assert.equal(await page.locator('#setup-prompt').textContent(), setupPrompt, 'the prompt copied is the approved prompt');
  }
}

for (const width of [390, 768, 1440]) for (const route of ['/', '/changelog']) {
  test(`${route} at ${width}: approved copy, local resources, dark only, static reduced motion, accessibility`, async () => {
    const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce', colorScheme: 'light' });
    try {
      const page = await context.newPage();
      const errors = [], requests = [];
      page.on('pageerror', error => errors.push(String(error)));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      page.on('request', request => requests.push(request.url()));
      page.on('response', response => { if (!response.ok()) errors.push(`HTTP ${response.status()}`); });
      await page.goto(origin + route);
      await page.waitForSelector('main[data-ready="true"]');
      await checkCopy(page, route);
      assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--ow-color-canvas').trim()), '#0e0f11', 'the app\'s shared tokens are loaded');
      assert.equal(await page.evaluate(() => getComputedStyle(document.body).backgroundColor), 'rgb(14, 15, 17)', 'the page paints the token canvas');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'no page overflow');
      assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme), 'dark');
      const background = await page.locator('body').evaluate(el => getComputedStyle(el).background);
      await page.emulateMedia({ colorScheme: 'dark' });
      assert.equal(await page.locator('body').evaluate(el => getComputedStyle(el).background), background, 'preference cannot change the dark design');
      assert.equal(await page.evaluate(() => document.getAnimations().filter(animation => animation.playState === 'running').length), 0, 'reduced motion is static');
      assert.equal(await page.evaluate(() => document.fonts.check('16px Geist') && document.fonts.check('16px GeistMono')), true);
      await page.addScriptTag({ path: axe });
      const report = await page.evaluate(() => axe.run(document));
      assert.deepEqual(report.violations.map(({ id, nodes }) => ({ id, nodes: nodes.map(node => node.target) })), [], 'all axe rules');
      assert.deepEqual(errors, []);
      assert.equal(requests.every(url => url.startsWith(origin + '/') || url.startsWith('data:')), true, 'no external resource or product API reads');
    } finally { await context.close(); }
  });
}

for (const width of [390, 768, 1440]) test(`the prompt at ${width} never scrolls horizontally, keeps its whole text and its buttons take focus`, async () => {
  const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
  try {
    await page.goto(origin);
    await page.waitForSelector('main[data-ready="true"]');
    assert.equal(await page.locator('.prompt').evaluate(el => el.scrollWidth <= el.clientWidth), true, 'the prompt has no horizontal scroll');
    assert.equal(await page.locator('#setup-prompt').textContent(), setupPrompt, 'the preview keeps the whole prompt');
    for (const control of [page.locator('.copy'), page.locator('.star')]) {
      await control.focus();
      assert.equal(await control.evaluate(el => el === document.activeElement), true);
      const box = await control.boundingBox();
      assert.ok(box.height >= 44 && box.x >= 0 && box.x + box.width <= width, 'a whole touch target on screen');
    }
  } finally { await page.close(); }
});

test('copy guard refuses changed or added claims, evidence links and command bytes', async () => {
  const page = await browser.newPage();
  try {
    for (const route of ['/', '/changelog']) {
      const mutations = [
        () => page.locator('h1').evaluate(el => { el.textContent = 'Unsupported promise'; }),
        () => page.locator('main').evaluate(el => { el.append(' An unapproved capability.'); }),
        () => page.locator('main').evaluate(el => { const extra = document.createElement('p'); extra.hidden = true; extra.textContent = 'Unapproved hidden claim.'; el.append(extra); }),
        () => page.locator('main a').first().evaluate(el => { el.href = 'https://example.com/'; }),
      ];
      if (route === '/') mutations.push(() => page.locator('#setup-prompt').evaluate(el => { el.textContent += ' '; }), () => page.locator('.intro .tl').first().evaluate(el => { el.textContent = 'Unapproved feature'; }));
      for (const mutate of mutations) {
        await page.goto(origin + route);
        await page.waitForSelector('main[data-ready="true"]');
        await checkCopy(page, route);
        await mutate();
        await assert.rejects(checkCopy(page, route), { name: 'AssertionError' });
      }
    }
  } finally { await page.close(); }
});

test('keyboard and emulated touch navigate the menu and changelog', async () => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, reducedMotion: 'reduce' });
  try {
    const page = await context.newPage();
    await page.goto(origin);
    await page.waitForSelector('main[data-ready="true"]');
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('.skip').evaluate(el => el === document.activeElement), true);
    await page.locator('.menu-toggle').focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'), 'true');
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('#navigation a').first().evaluate(el => el === document.activeElement), true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'), 'false');
    assert.equal(await page.locator('.menu-toggle').evaluate(el => el === document.activeElement), true);
    await page.locator('.menu-toggle').tap();
    await page.locator('#navigation a').first().tap();
    await page.waitForURL(origin + '/changelog/');
    await page.waitForSelector('main[data-ready="true"]');
    await checkCopy(page, '/changelog');
    await page.locator('.menu-toggle').tap();
    await page.locator('#navigation a').first().tap();
    await page.waitForURL(origin + '/');
    await page.waitForSelector('main[data-ready="true"]');
    await page.locator('#setup-prompt').evaluate(el => {
      const selection = getSelection();
      const range = document.createRange();
      range.selectNodeContents(el);
      selection.removeAllRanges(); selection.addRange(range);
    });
    assert.equal(await page.evaluate(() => getSelection().toString()), setupPrompt, 'the prompt can be selected and copied by hand');
  } finally { await context.close(); }
});

for (const [width, route] of [[1440, '/'], [390, '/changelog']]) test(`⌘K palette at ${width} on ${route}: opens by key and button, filters, jumps, closes, passes axe`, async () => {
  const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: width === 390, reducedMotion: 'reduce' });
  try {
    const page = await context.newPage();
    await page.goto(origin + route);
    await page.waitForSelector('main[data-ready="true"]');
    const dialog = page.locator('dialog#jump');
    assert.equal(await dialog.evaluate(el => el.open), false);
    await page.keyboard.press('Control+k');
    assert.equal(await dialog.evaluate(el => el.open), true, 'Ctrl+K opens it');
    assert.equal(await page.locator('#jump input').evaluate(el => el === document.activeElement), true, 'focus moves to the search');
    await page.addScriptTag({ path: axe });
    const report = await page.evaluate(() => axe.run(document));
    assert.deepEqual(report.violations.map(({ id, nodes }) => ({ id, nodes: nodes.map(node => node.target) })), [], 'axe with the palette open');
    await page.keyboard.press('Escape');
    assert.equal(await dialog.evaluate(el => el.open), false, 'Escape closes it');
    await page.waitForFunction(() => document.activeElement === document.querySelector('.cmdk'), null, { timeout: 5000 });
    assert.equal(await page.locator('.cmdk').evaluate(el => el === document.activeElement), true, 'focus returns to the bar');
    if (width === 390) await page.locator('.cmdk').tap(); else await page.locator('.cmdk').click();
    assert.equal(await dialog.evaluate(el => el.open), true, 'the bar opens it');
    await page.keyboard.type('building');
    assert.deepEqual(await page.locator('#jump li:not([hidden]) a').allTextContents(), ['Building next'], 'filters by name');
    await page.keyboard.type('zzz');
    assert.equal(await page.locator('.palette-empty').isVisible(), true, 'says when nothing matches');
    for (let i = 0; i < 3; i++) await page.keyboard.press('Backspace');
    await page.keyboard.press('Enter');
    await page.waitForURL(origin + '/#next');
    assert.equal(await dialog.evaluate(el => el.open), false, 'following a result closes it');
  } finally { await context.close(); }
});

for (const [route, selectedName, installId] of [
  ['/', 'Building next', 'jump-option-1'],
  ['/changelog', '0.0.4 — Start new threads, with files', 'jump-option-8'],
]) test(`R3: palette selection is exposed to assistive technology on ${route}`, async () => {
  const page = await browser.newPage({ reducedMotion: 'reduce' });
  try {
    await page.goto(origin + route);
    await page.waitForSelector('main[data-ready="true"]');
    const input = page.locator('#jump input');
    await page.keyboard.press('Control+k');
    await page.keyboard.press('ArrowDown');
    assert.equal(await page.locator('#jump a.active').textContent(), selectedName, 'the supported arrow path selects the second destination');
    assert.equal(await input.getAttribute('aria-activedescendant'), 'jump-option-1', 'the input identifies the selected destination');
    assert.equal(await input.getAttribute('role'), 'combobox');
    assert.equal(await input.getAttribute('aria-controls'), 'jump-results');
    assert.equal(await input.getAttribute('aria-expanded'), 'true');
    assert.equal(await input.evaluate(el => el === document.activeElement), true);
    assert.equal(await page.locator('#jump-results').getAttribute('role'), 'listbox');
    assert.equal(await page.locator('#jump-option-1').getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator('#jump [role="option"][aria-selected="true"]').count(), 1);

    const session = await page.context().newCDPSession(page);
    const { nodes } = await session.send('Accessibility.getFullAXTree');
    const combo = nodes.find(node => node.role?.value === 'combobox' && node.name?.value === 'Search the site');
    assert.ok(combo, 'the browser exposes the search as a named combobox');
    const relation = combo.properties.find(property => property.name === 'activedescendant');
    assert.ok(relation?.value.relatedNodes.some(node => node.idref === 'jump-option-1'), 'the browser AX tree exposes the active-result relation');
    const option = nodes.find(node => node.role?.value === 'option' && node.name?.value === selectedName);
    assert.equal(option?.properties.find(property => property.name === 'selected')?.value.value, true, 'the active destination is selected in the AX tree');
    await session.detach();
    await page.addScriptTag({ path: axe });
    const report = await page.evaluate(() => axe.run(document.querySelector('#jump')));
    assert.deepEqual(report.violations.map(violation => violation.id), [], 'palette accessibility rules');

    await page.keyboard.press('ArrowUp');
    assert.equal(await input.getAttribute('aria-activedescendant'), 'jump-option-0');
    await input.fill('Building');
    assert.equal(await input.getAttribute('aria-activedescendant'), installId, 'filtering preserves the destination ID');
    await input.fill('no matching destination');
    assert.equal(await input.getAttribute('aria-activedescendant'), null, 'no stale active-result relation when empty');
    assert.equal(await page.locator('#jump [aria-selected="true"]').count(), 0);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelector('#jump input').getAttribute('aria-expanded') === 'false');
    assert.equal(await input.getAttribute('aria-activedescendant'), null);
    assert.equal(await page.locator('.cmdk').evaluate(el => el === document.activeElement), true);
    await page.keyboard.press('Control+k');
    assert.equal(await input.getAttribute('aria-activedescendant'), 'jump-option-0', 'reopening resets selection');
    await input.fill('Building');
    assert.equal(await input.getAttribute('aria-activedescendant'), installId);
    await page.keyboard.press('Enter');
    await page.waitForURL(origin + '/#next');
    await page.waitForSelector('main[data-ready="true"]');
    await page.waitForFunction(() => document.querySelector('#jump input').getAttribute('aria-expanded') === 'false');
  } finally { await page.close(); }
});

test('#1190: the landing\'s visible text is shorter, with no live-test or evidence label', async () => {
  const page = await browser.newPage({ reducedMotion: 'reduce' });
  try {
    await page.goto(origin);
    await page.waitForSelector('main[data-ready="true"]');
    const visible = normalize(await page.locator('main').innerText());
    assert.ok(visible.length < landingCharsBefore1190, `${visible.length} characters, before ${landingCharsBefore1190}`);
    const all = await page.locator('body').textContent();
    for (const label of bannedLanding) assert.doesNotMatch(all, label);
  } finally { await page.close(); }
});

// #1190, W2: the hero's second action is a prompt for your agent, copied with
// one click or one key, with a visible and announced Copied state.
for (const width of [390, 1440]) test(`#1190: the setup prompt copies by click, Enter and Space at ${width}`, async () => {
  const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce', hasTouch: width === 390 });
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin });
  try {
    const page = await context.newPage();
    const button = page.locator('.hero .copy');
    const status = page.locator('.hero [role="status"]');
    for (const press of [() => (width === 390 ? button.tap() : button.click()), () => page.keyboard.press('Enter'), () => page.keyboard.press('Space')]) {
      await page.goto(origin);
      await page.waitForSelector('main[data-ready="true"]');
      await page.evaluate(() => navigator.clipboard.writeText('unchanged'));
      assert.equal(await page.locator('.hero #setup-prompt').textContent(), setupPrompt, 'the prompt shown is the prompt copied');
      assert.equal(await button.textContent(), 'Copy the prompt');
      assert.equal(await status.textContent(), '');
      const box = await button.boundingBox();
      assert.ok(box.height >= 44 && box.x >= 0 && box.x + box.width <= width, 'a whole touch target on screen');
      assert.equal(await page.locator('.hero .prompt').evaluate(el => el.scrollWidth <= el.clientWidth), true, 'the prompt never scrolls sideways');
      await button.focus();
      await press();
      await page.waitForSelector('.hero .copy[data-state="copied"]');
      assert.equal(await button.textContent(), 'Copied');
      assert.equal(await status.textContent(), 'Prompt copied');
      assert.equal(await page.evaluate(() => navigator.clipboard.readText()), setupPrompt);
      assert.equal(await button.evaluate(el => el === document.activeElement), true, 'focus stays on the button');
    }
  } finally { await context.close(); }
});

// #1109 (IF9): the hero's first action copies the one install line. #2293: the line under it says
// OpenWiz is free now and paid plans come later, with CloudRoom and model charges separate. It links
// CloudRoom's own pricing page with no referral (none is verified, so none is guessed, and the page
// says verification is unavailable), and the landing offers no upgrade, price, trial or checkout.
for (const width of [390, 1440]) test(`#1109/#2293: install line first, then free now and paid plans later at ${width}`, async () => {
  const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce', hasTouch: width === 390 });
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin });
  try {
    const page = await context.newPage();
    await page.goto(origin);
    await page.waitForSelector('main[data-ready="true"]');
    const first = page.locator('main button, main a').first();
    assert.equal(await first.textContent(), 'Copy the prompt', 'the first action on the page copies the install line');
    await (width === 390 ? first.tap() : first.click());
    await page.waitForSelector('.hero .copy[data-state="copied"]');
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), 'Install OpenWiz from github.com/openwizdev/openwiz');
    const cost = page.locator('.hero .cost');
    assert.equal(normalize(await cost.innerText()), costLine);
    const link = cost.locator('a');
    assert.equal(await link.count(), 1);
    const href = await link.getAttribute('href');
    assert.equal(href, cloudroomHref);
    const url = new URL(href);
    assert.equal(url.search + url.hash, '', 'no referral code, parameter or fragment is guessed');
    assert.equal(await link.getAttribute('rel'), 'noopener');
    const box = await link.boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= width, 'the link is on screen');
    assert.doesNotMatch(await page.locator('body').textContent(), notOffered, 'no paid offer or OpenWiz upgrade on the landing');
  } finally { await context.close(); }
});

test('#1190: Copied resets by itself, and a refused copy selects the prompt instead', async () => {
  const context = await browser.newContext({ reducedMotion: 'reduce' });
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin });
  try {
    const page = await context.newPage();
    await page.goto(origin);
    await page.waitForSelector('main[data-ready="true"]');
    const button = page.locator('.hero .copy');
    const status = page.locator('.hero [role="status"]');
    await button.click();
    await page.waitForSelector('.hero .copy[data-state="copied"]');
    await page.waitForSelector('.hero .copy:not([data-state])', { timeout: 5000 });
    assert.equal(await button.textContent(), 'Copy the prompt');
    assert.equal(await button.getAttribute('data-state'), null);
    assert.equal(await status.textContent(), '');

    await page.evaluate(() => { navigator.clipboard.writeText = () => Promise.reject(new DOMException('refused', 'NotAllowedError')); });
    await button.click();
    await page.waitForSelector('.hero .copy[data-state="failed"]');
    assert.equal(await button.textContent(), 'Copy failed');
    assert.equal(await status.textContent(), 'Copy failed. The prompt is selected.');
    assert.equal(await page.evaluate(() => getSelection().toString()), setupPrompt);
    await page.addScriptTag({ path: axe });
    const report = await page.evaluate(() => axe.run(document));
    assert.deepEqual(report.violations.map(violation => violation.id), [], 'axe in the failed state');
  } finally { await context.close(); }
});

// #1352 (Jake, LR1): the intro is one ~6 s sequence that then holds; nothing in it loops; it opens
// on the typed idea alone; reduced motion shows the rest frame at once; the stage keeps its size.
for (const width of [390, 1440]) test(`#1352: the intro at ${width} is one finite sequence that holds, and reduced motion shows the rest frame`, async () => {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  try {
    const page = await context.newPage();
    await page.goto(origin);
    await page.waitForSelector('main[data-ready="true"]');
    const timing = await page.evaluate(() => {
      const intro = document.querySelector('.intro');
      const own = document.getAnimations().filter(a => a.effect?.target && intro.contains(a.effect.target));
      const ends = own.map(a => a.effect.getComputedTiming().endTime);
      const size = () => { const r = intro.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; };
      const seek = ms => own.forEach(a => { a.pause(); a.currentTime = ms; });
      const shown = sel => [...intro.querySelectorAll(sel)].map(el => getComputedStyle(el).opacity);
      seek(0); const start = { size: size(), done: shown('.t .done'), tickets: shown('.t'), idea: shown('.typed') };
      seek(8000); const rest = { size: size(), done: shown('.t .done'), approved: shown('.approved'), note: shown('.n4') };
      return { count: own.length, infinite: ends.filter(end => !Number.isFinite(end)).length, last: Math.max(...ends), start, rest };
    });
    assert.ok(timing.count > 0, 'the intro animates');
    assert.equal(timing.infinite, 0, 'nothing in the stage loops');
    assert.ok(timing.last <= 6500, `the sequence ends by 6.5 s (${timing.last} ms)`);
    assert.deepEqual(timing.start.size, timing.rest.size, 'the stage keeps its size from the first frame');
    assert.deepEqual(timing.start.idea, ['1'], 'it opens on the typed idea');
    assert.ok(timing.start.tickets.every(o => o === '0') && timing.start.done.every(o => o === '0'), 'no ticket before the plan');
    assert.ok(timing.rest.done.length === 5 && timing.rest.done.every(o => o === '1'), 'it rests with all five merged');
    assert.deepEqual([...timing.rest.approved, ...timing.rest.note], ['1', '1'], 'the approval and the last note stay');

    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(origin);
    await page.waitForSelector('main[data-ready="true"]');
    const still = await page.evaluate(() => {
      const intro = document.querySelector('.intro');
      return { running: document.getAnimations().filter(a => a.playState === 'running' && intro.contains(a.effect.target)).length,
        done: [...intro.querySelectorAll('.t .done')].map(el => getComputedStyle(el).opacity) };
    });
    assert.equal(still.running, 0, 'reduced motion: no movement');
    assert.deepEqual(still.done, ['1', '1', '1', '1', '1'], 'reduced motion: the rest frame at once');
  } finally { await context.close(); }
});

// #1205 R1: ten destinations overflow the palette's list; the selected one must stay in view.
for (const [width, route] of [[390, '/changelog'], [1440, '/changelog'], [1440, '/']]) test(`R1: keyboard selection stays visible in the palette at ${width} on ${route}`, async () => {
  const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
  try {
    await page.goto(origin + route);
    await page.waitForSelector('main[data-ready="true"]');
    await page.keyboard.press('Control+k');
    const count = await page.locator('#jump-results a').count();
    const inView = () => page.evaluate(() => {
      const list = document.querySelector('#jump-results').getBoundingClientRect();
      const option = document.querySelector('#jump a.active').getBoundingClientRect();
      return option.top >= list.top && option.bottom <= list.bottom;
    });
    const activeId = () => page.locator('#jump input').getAttribute('aria-activedescendant');
    if (route === '/changelog') assert.equal(count, 10, 'six versions and four site destinations overflow the list');
    await page.keyboard.press('ArrowUp');
    assert.equal(await activeId(), `jump-option-${count - 1}`, 'ArrowUp wraps to the last destination');
    assert.equal(await inView(), true, 'the wrapped-to last destination is visible');
    await page.keyboard.press('ArrowDown');
    assert.equal(await activeId(), 'jump-option-0', 'ArrowDown wraps to the first destination');
    assert.equal(await inView(), true, 'the wrapped-to first destination is visible');
    for (let i = 1; i < count; i++) {
      await page.keyboard.press('ArrowDown');
      assert.equal(await activeId(), `jump-option-${i}`);
      assert.equal(await inView(), true, `destination ${i} is visible when selected`);
    }
    assert.equal(await page.evaluate(() => scrollY), 0, 'only the list scrolls, never the page behind the palette');
  } finally { await page.close(); }
});

// #1199: one section per version in the approved look (Jake, 2026-11-06).
// Private record: https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6705218593
for (const width of [390, 1440]) test(`#1199: /changelog at ${width}: one section per version, solid numerals, readable dates, numbered lines`, async () => {
  const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
  try {
    await page.goto(origin + '/changelog');
    await page.waitForSelector('main[data-ready="true"]');
    const sections = await page.locator('main article.release').evaluateAll(articles => articles.map(article => {
      const numeral = article.querySelector('.release-version'), n = getComputedStyle(numeral);
      const date = getComputedStyle(article.querySelector('time'));
      const lines = [...article.querySelectorAll('.release-lines li')];
      const heading = article.querySelector('h2').getBoundingClientRect(), box = numeral.getBoundingClientRect();
      return {
        id: article.id, size: parseFloat(n.fontSize), color: n.color, stroke: parseFloat(n.webkitTextStrokeWidth),
        dateSize: parseFloat(date.fontSize), others: Math.max(parseFloat(getComputedStyle(article.querySelector('h2')).fontSize), parseFloat(date.fontSize), ...lines.map(li => parseFloat(getComputedStyle(li).fontSize))), hairline: getComputedStyle(article).borderTopWidth,
        numbers: lines.map(li => getComputedStyle(li, '::before').content),
        between: lines.slice(1).map(li => getComputedStyle(li).borderTopWidth),
        beside: box.right <= heading.left, above: box.bottom <= heading.top,
      };
    }));
    assert.deepEqual(sections.map(section => section.id), ['v0.0.5', 'v0.0.4', 'v0.0.3', 'v0.0.2', 'v0.0.1', 'v0.0.0'], 'six sections, newest first');
    sections.forEach((section, index) => {
      assert.ok(section.size >= (width === 390 ? 30 : 44), `${section.id}: a large numeral (${section.size}px)`);
      assert.ok(section.size > section.others, `${section.id}: the numeral is the section's largest type (${section.size}px > ${section.others}px)`);
      if (index === 0) assert.deepEqual([section.color, section.stroke], ['rgb(167, 139, 250)', 0], 'the newest numeral is solid accent');
      else assert.deepEqual([section.color, section.stroke], ['rgb(182, 189, 200)', 0], `${section.id}: a secondary solid numeral`);
      assert.ok(section.dateSize >= 15, `${section.id}: the date is readable (${section.dateSize}px)`);
      assert.equal(section.hairline, '1px', `${section.id}: a hairline separates the section`);
      assert.ok(section.numbers.every(content => content.includes('decimal-leading-zero')), `${section.id}: lines are numbered 01, 02…`);
      assert.ok(section.between.every(border => border === '0px'), `${section.id}: open rhythm, no rule between lines`);
      assert.equal(width === 390 ? section.above : section.beside, true, `${section.id}: the numeral is ${width === 390 ? 'above' : 'left of'} the headline`);
    });
  } finally { await page.close(); }
});
