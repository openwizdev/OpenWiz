// #2292: the app's feedback handoff and share (contracts/feedback.v1.md,
// "Two entry routes" and "Sharing"), on a recording clipboard. A copy writes
// the clipboard once, with exactly the previewed bytes, only after an explicit
// copy; cancel, an edit, a repeat or a copy without a preview writes nothing.
// Expected texts are written by hand from the contract.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { appendFileSync, cpSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { BODY_MAX, Copier, feedbackProblem, handoffText, shareProblem, shareText, SHARE_URL } from '../../src/feedback.ts';

function recording(fail = false) {
  const writes: string[] = [];
  return { writes, clipboard: { writeText: async (t: string) => { writes.push(t); if (fail) throw new Error('denied'); } } };
}

const TITLE = 'Plan page hides the approve button on a narrow phone';
const BODY = 'On a 360-pixel screen the approve button sits under the footer.';

test('the handoff holds a fixed instruction and only the chosen words', () => {
  assert.equal(handoffText(`  ${TITLE} `, `${BODY}\r\n\r\n`), [
    'Please send this as public feedback about OpenWiz with the OpenWiz feedback skill (openwiz:feedback).',
    'It becomes one public issue on openwizdev/openwiz, under my own GitHub login.',
    'Show me the exact preview first, and create nothing until I say yes.',
    '',
    `Title: ${TITLE}`,
    '',
    'Body:',
    BODY,
  ].join('\n'));
});

test('feedback outside the contract is refused before any preview', () => {
  assert.equal(feedbackProblem(TITLE, BODY), null);
  const cases: [string, string][] = [[' ', BODY], ['a\nb', BODY], ['t'.repeat(257), BODY], [TITLE, ' \n'], [TITLE, 'b'.repeat(BODY_MAX + 1)],
    [TITLE, `x\nOpenWiz feedback operation ${'a'.repeat(32)}`]];
  for (const [t, b] of cases) {
    assert.notEqual(feedbackProblem(t, b), null, JSON.stringify([t.slice(0, 20), b.slice(0, 20)]));
  }
  assert.equal(feedbackProblem('t'.repeat(256), 'b'.repeat(BODY_MAX)), null);
});

test('copy writes exactly the previewed bytes once, and only after the copy', async () => {
  const r = recording();
  const c = new Copier(r.clipboard);
  await c.copy();
  assert.deepEqual(r.writes, [], 'no preview, no write');
  const bytes = handoffText(TITLE, BODY);
  c.show(bytes);
  assert.deepEqual(c.snapshot(), { phase: 'previewing', bytes });
  assert.deepEqual(r.writes, [], 'a preview alone writes nothing');
  await c.copy();
  await c.copy();
  assert.deepEqual(r.writes, [bytes]);
  assert.deepEqual(c.snapshot(), { phase: 'copied', bytes });
});

test('cancel and an edit after the preview write nothing', async () => {
  const r = recording();
  const c = new Copier(r.clipboard);
  c.show(shareText('Try OpenWiz.'));
  c.cancel();
  await c.copy();
  assert.deepEqual(c.snapshot(), { phase: 'editing' });
  c.show(handoffText(TITLE, BODY));
  c.cancel(); // the owner changed a word
  await c.copy();
  assert.deepEqual(r.writes, []);
});

test('a refused clipboard is not copied, and never says so', async () => {
  const r = recording(true);
  const c = new Copier(r.clipboard);
  c.show('x');
  await c.copy();
  assert.deepEqual(c.snapshot(), { phase: 'not_copied', bytes: 'x' });
  const none = new Copier(null);
  none.show('x');
  await none.copy();
  assert.equal(none.snapshot().phase, 'not_copied');
});

test('a share is the owner\'s text and the one allowlisted URL; links and addresses are refused', async () => {
  assert.equal(SHARE_URL, 'https://github.com/openwizdev/openwiz');
  assert.equal(shareText('  Try OpenWiz with me.\r\n'), 'Try OpenWiz with me.\n\nhttps://github.com/openwizdev/openwiz');
  assert.equal(shareProblem('Try OpenWiz with me.'), null);
  for (const t of ['', '  ', 'see https://example.com', 'open http://localhost:7370', 'www.example.com', 'at 192.168.1.10',
    'file:///home/synthetic-user/secret-project', 'synthetic-token-000000 at localhost']) {
    assert.notEqual(shareProblem(t), null, t);
  }
});

// #2292 (J28): npm run check allows exactly one <textarea> in
// FeedbackShare.tsx and exactly the share URL literal, once, in
// src/feedback.ts. Each planted violation runs the real check on a scratch
// copy of the web sources and must be refused with its own problem line.
const WEB = new URL('../../', import.meta.url).pathname;
function checkWith(plant: (root: string) => void): { code: number | null; out: string } {
  const top = mkdtempSync(join(tmpdir(), 'feedback-check-'));
  try {
    const root = join(top, 'apps/web');
    for (const d of ['scripts', 'src', 'pages', 'styles']) cpSync(join(WEB, d), join(root, d), { recursive: true });
    symlinkSync(join(WEB, 'node_modules'), join(root, 'node_modules'));
    symlinkSync(join(WEB, '../../contracts'), join(top, 'contracts'));
    plant(root);
    const run = spawnSync(process.execPath, [join(root, 'scripts/check.mjs')], { encoding: 'utf8' });
    return { code: run.status, out: run.stdout + run.stderr };
  } finally {
    rmSync(top, { recursive: true, force: true });
  }
}
const add = (root: string, rel: string, text: string) => appendFileSync(join(root, rel), text);
const swap = (root: string, rel: string, from: string, to: string) => {
  const text = readFileSync(join(root, rel), 'utf8');
  assert.ok(text.includes(from), `${rel} holds ${from}`);
  writeFileSync(join(root, rel), text.replace(from, to));
};
const URL_LITERAL = "'https://github.com/openwizdev/openwiz'";

test('the feedback exceptions pass, and every other textarea or share URL is still refused', () => {
  assert.equal(checkWith(() => {}).code, 0, 'the unchanged copy passes');
  const cases: [string, (root: string) => void, RegExp][] = [
    ['a textarea in another component', (r) => add(r, 'src/components/Ui.tsx', '\nexport const Planted = () => <textarea />;\n'), /U14: <textarea> in .*src\/components\/Ui\.tsx/],
    ['a second textarea in FeedbackShare.tsx', (r) => add(r, 'src/components/FeedbackShare.tsx', '\nexport const Planted = () => <textarea />;\n'), /U14: <textarea> in .*FeedbackShare\.tsx.*FeedbackShare\.tsx/],
    ['the share URL in another file', (r) => add(r, 'src/components/FeedbackShare.tsx', `\nexport const planted = ${URL_LITERAL};\n`), /FeedbackShare\.tsx:\d+: an absolute or script URL: https:\/\/github\.com\/openwizdev\/openwiz/],
    ['another URL in src/feedback.ts', (r) => add(r, 'src/feedback.ts', "\nexport const planted = 'https://github.com/openwizdev/openwiz/issues';\n"), /src\/feedback\.ts:\d+: an absolute or script URL/],
    ['the share URL twice in src/feedback.ts', (r) => add(r, 'src/feedback.ts', `\nexport const planted = ${URL_LITERAL};\n`), /src\/feedback\.ts: the share URL .* appears 2 times/],
    ['the share URL as a template in src/feedback.ts', (r) => swap(r, 'src/feedback.ts', URL_LITERAL, '`https://github.com/openwizdev/openwiz`'), /src\/feedback\.ts:\d+: an absolute or script URL/],
  ];
  for (const [name, plant, refusal] of cases) {
    const { code, out } = checkWith(plant);
    assert.equal(code, 1, `${name}: refused`);
    assert.match(out, refusal, `${name}: ${out}`);
  }
});
