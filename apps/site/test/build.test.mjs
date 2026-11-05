import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, relative } from 'node:path';
import test from 'node:test';
import { landing, changelog, changelogEntries, landingLinks, changelogLinks, bannedLanding, setupPrompt, stage, worksToday, buildingNext } from './approved-copy.mjs';

const site = fileURLToPath(new URL('../', import.meta.url));
const files = ['changelog/index.html', 'fonts/Geist-var.woff2', 'fonts/GeistMono-var.woff2', 'fonts/OFL.txt', 'fonts/Virgil-OFL.txt', 'fonts/Virgil.woff2', 'index.html', 'script.js', 'style.css', 'tokens.css'];

test('static export contains exactly the ten reviewed runtime files, byte for byte', () => {
  execFileSync(process.execPath, ['build.mjs'], { cwd: site, stdio: 'pipe' });
  assert.deepEqual(readdirSync(`${site}/dist`, { recursive: true, withFileTypes: true })
    .filter(entry => entry.isFile()).map(entry => relative(join(site, 'dist'), join(entry.parentPath, entry.name))).sort(), files);
  for (const file of files) assert.deepEqual(readFileSync(`${site}/dist/${file}`), readFileSync(`${site}/${file}`), file);
});

// A cheap source check before the browser's rendered/hidden-text copy checks.
// These pages use literal HTML, with only these named character references.
const decode = html => html.replace(/&(?:amp|lt|gt|quot|apos);/g, entity => ({
  '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&apos;': "'",
})[entity]);
const textBytes = html => decode(html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]*>/g, '')).replace(/\s/g, '');
// #1352: the intro is one labelled illustration inside the hero's figure; its synthetic text is
// checked apart from the page's claims, and nothing else may hide inside it.
const stageRegion = /<div class="intro\b[^>]*>([^]*?)<\/div><figcaption/;
function checkSource(html, expectedText, expectedLinks) {
  let main = html.match(/<main\b[^>]*>([^]*?)<\/main>/)?.[1];
  assert.ok(main, 'page contains main');
  if (expectedText === landing) {
    const illustration = main.match(stageRegion)?.[1];
    assert.ok(illustration, 'the landing has its intro illustration');
    assert.equal(textBytes(illustration), stage.replace(/\s/g, ''), 'the illustration holds only its approved synthetic text');
    assert.doesNotMatch(illustration, /<a\b|href=/, 'the illustration links nowhere');
    main = main.replace(stageRegion, '<figcaption');
  }
  assert.equal(textBytes(main), expectedText.replace(/\s/g, ''), 'approved claim text, including hidden text');
  assert.deepEqual([...main.matchAll(/<a\b[^>]*href="([^"]*)"/g)].map(match => decode(match[1])), expectedLinks, 'approved links');
}

for (const [file, copy, links] of [
  ['index.html', landing, landingLinks], ['changelog/index.html', changelog, changelogLinks],
]) test(`${file}: static release copy and links match the approved literals`, () => {
  const html = readFileSync(`${site}/${file}`, 'utf8');
  checkSource(html, copy, links);
  for (const changed of [
    html.replace('>0.0.3', '>9.9.9'),
    html.replace('</main>', '<p hidden>Unapproved claim.</p></main>'),
    html.replace(/(<main\b[^]*?<a\b[^>]*href=")[^"]*/, '$1https://example.com/'),
    ...(file === 'index.html' ? [html.replace('>Theme tokens<', '>Unapproved feature<'), html.replace('<figcaption', '<p hidden>Hidden in the stage.</p></div><figcaption').replace(/<\/div><p hidden>/, '<p hidden>')] : []),
  ]) assert.throws(() => checkSource(changed, copy, links), { name: 'AssertionError' });
  if (file === 'index.html') {
    assert.equal(decode(html.match(/<p\b[^>]*id="setup-prompt"[^>]*>([^]*?)<\/p>/)?.[1].replace(/<[^>]*>/g, '') ?? ''), setupPrompt, 'the prompt in the page is the approved prompt');
  }
});

test('#1199: one section per version, newest first: numeral, date, headline, 3 to 6 numbered lines, one link; no combined entry', () => {
  const html = readFileSync(`${site}/changelog/index.html`, 'utf8');
  const main = html.match(/<main\b[^>]*>([^]*?)<\/main>/)[1];
  for (const gone of ['0.0.3–0.0.5', '0.0.3-0.0.5', 'Publication date pending', 'Staged public update', 'Export validation', 'Fixture test']) {
    assert.ok(!html.includes(gone), `no "${gone}"`);
  }
  const words = decode(main.replace(/<[^>]*>/g, ' ')).replace(/\s+/g, ' ');
  for (const label of bannedLanding) assert.doesNotMatch(words, label, 'no test-class, pending or evidence wording');
  const entries = [...main.matchAll(/<article class="release" id="([^"]+)"[^>]*>([^]*?)<\/article>/g)].map(([, id, body]) => {
    const time = body.match(/<time datetime="([^"]*)">([^<]*)<\/time>/);
    const lines = [...(body.match(/<ol class="release-lines">([^]*?)<\/ol>/)?.[1] ?? '').matchAll(/<li>([^]*?)<\/li>/g)].map(match => decode(match[1].replace(/<[^>]*>/g, '')));
    const links = [...body.matchAll(/<a\b[^>]*href="([^"]*)"/g)].map(match => match[1]);
    return [id, body.match(/<p class="release-version">([^<]*)<\/p>/)?.[1], time?.[1], time?.[2], decode(body.match(/<h2>([^<]*)<\/h2>/)?.[1] ?? ''), lines, links.length === 1 && body.trimEnd().endsWith('</a></div>') ? links[0] : links];
  });
  assert.deepEqual(entries, changelogEntries, 'six sections in order, each ending in its one link');
  for (const [id, , , , , lines] of entries) assert.ok(lines.length >= 3 && lines.length <= 6, `${id}: 3 to 6 lines`);
  assert.equal((main.match(/<article\b/g) ?? []).length, 6, 'exactly six sections');
  const palette = [...html.matchAll(/<a href="(#v[^"]*)">([^<]*)<\/a>/g)].map(([, href, name]) => [href, decode(name)]);
  assert.deepEqual(palette, changelogEntries.map(([id, version, , , headline]) => [`#${id}`, `${version} — ${headline}`]), 'the jump palette lists each version');
});

// #1190, W1: the landing carries no staged/pending note and no live-test or
// evidence label, in its text, its hidden text or any text attribute.
function checkWording(html) {
  const text = decode(html.replace(/<!--[^]*?-->/g, '').replace(/<[^>]*>/g, ' '));
  const attributes = [...html.matchAll(/\s(?:aria-[a-z]+|title|alt|content|placeholder|value)="([^"]*)"/g)].map(match => decode(match[1]));
  for (const words of [text, ...attributes]) for (const label of bannedLanding) assert.doesNotMatch(words, label);
}
test('#1190: the landing has no staged, pending, live-test or evidence wording', () => {
  const html = readFileSync(`${site}/index.html`, 'utf8');
  checkWording(html);
  for (const planted of ['Fixture test:', 'Live observation, with gaps', 'LIVE-0.0.4', 'recorded gaps', 'No PACP conformance', 'pending live test', 'staged public update', 'Evidence ↗']) {
    assert.throws(() => checkWording(html.replace('</main>', `<p hidden>${planted}</p></main>`)), { name: 'AssertionError' }, planted);
    assert.throws(() => checkWording(html.replace('<main ', `<main aria-label="${planted}" `)), { name: 'AssertionError' }, planted);
  }
});

// #1190 W1 and #1352: Works today has one plain line for each published version, 0.0.1 to 0.0.5,
// each linking to the changelog; Building next has one plain line for each planned version, none a
// link and none already published. Nothing else claims a shipped feature.
function rows(html, id) {
  const section = html.match(new RegExp(`<section\\b[^>]*id="${id}"[^>]*>([^]*?)<\\/section>`))?.[1];
  assert.ok(section, `${id} section`);
  return [...section.matchAll(/<li\b[^>]*>([^]*?)<\/li>/g)].map(([, row]) => {
    assert.doesNotMatch(row, /<(?:ul|ol|li|br|strong|p)\b/, 'a row is one plain line');
    const text = [...row.matchAll(/<span\b[^>]*>([^<]*)<\/span>/g)].map(match => match[1]);
    assert.equal(text.length, 2, 'a version and one line');
    return { version: text[0], links: [...row.matchAll(/href="([^"]*)"/g)].map(match => match[1]) };
  });
}
function checkRows(html) {
  const works = rows(html, 'works'), next = rows(html, 'next');
  assert.deepEqual(works.map(row => row.version), worksToday);
  for (const row of works) assert.deepEqual(row.links, ['/changelog/'], `${row.version} links to the changelog`);
  assert.deepEqual(next.map(row => row.version), buildingNext);
  for (const row of next) assert.deepEqual(row.links, [], `${row.version} is not a link`);
  assert.equal(next.some(row => worksToday.includes(row.version)), false, 'nothing published is listed as next');
}
test('#1190 and #1352: Works today lists 0.0.1 to 0.0.5, Building next 0.0.6 to 0.0.14, one plain line each', () => {
  const html = readFileSync(`${site}/index.html`, 'utf8');
  checkRows(html);
  assert.throws(() => checkRows(html.replace(/(id="works"[^]*?<\/span>)(<\/a><\/li>)/, '$1<br>Second line.$2')), { name: 'AssertionError' });
  assert.throws(() => checkRows(html.replace(/<li><a href="\/changelog\/"><span class="v">0\.0\.5<\/span>[^]*?<\/li>/, '')), { name: 'AssertionError' });
  assert.throws(() => checkRows(html.replace('<span class="v">0.0.9</span>', '<span class="v">0.0.5</span>')), { name: 'AssertionError' });
});
