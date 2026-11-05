import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

test('CI classifies site paths only for the jobs that build and test the site', () => {
  const root = fileURLToPath(new URL('../../../', import.meta.url));
  const classified = execFileSync('sh', ['.github/actions/docs-only/classify.sh'], { cwd: root, input: 'apps/site/index.html\n', encoding: 'utf8' });
  assert.equal(classified, 'web-build web-test\n');
  for (const job of ['web-build', 'web-test']) {
    assert.equal(execFileSync('sh', ['.github/actions/docs-only/classify.sh', '--skips', job], { cwd: root, input: 'apps/site/index.html\n', encoding: 'utf8' }), '');
  }
  assert.equal(execFileSync('sh', ['.github/actions/docs-only/classify.sh', '--skips', 'rust'], { cwd: root, input: 'apps/site/index.html\n', encoding: 'utf8' }), 'apps/site/index.html\n');
});

// The app's shared design tokens, brought in unchanged (room/design-hill-climb
// at 56970e2e, apps/web/styles/tokens.css). A retune updates this hash; once
// the app's copy is on this branch, the two files must stay identical.
const TOKENS_SHA256 = 'b837fc82932d8a1e9578a2d1e2ef5148bb3beb2cd602491d26437f8d02f12393';
test('the site uses the app\'s design tokens byte for byte', () => {
  const site = readFileSync(new URL('../tokens.css', import.meta.url));
  assert.equal(createHash('sha256').update(site).digest('hex'), TOKENS_SHA256);
  const app = new URL('../../web/styles/tokens.css', import.meta.url);
  if (existsSync(app)) assert.deepEqual(site, readFileSync(app), 'apps/web/styles/tokens.css and apps/site/tokens.css differ');
  for (const font of ['Geist-var.woff2', 'GeistMono-var.woff2', 'OFL.txt']) {
    assert.deepEqual(readFileSync(new URL(`../fonts/${font}`, import.meta.url)), readFileSync(new URL(`../../web/public/fonts/${font}`, import.meta.url)), font);
  }
});

test('R1: CI runs separate site and release jobs with the pinned Python fallback', () => {
  const workflow = readFileSync(new URL('../../../.github/workflows/ci.yml', import.meta.url), 'utf8');
  const runner = readFileSync(new URL('../../../.github/actions/docs-only/run.py', import.meta.url), 'utf8');
  const fallback = readFileSync(new URL('../../../.github/actions/docs-only/python.sh', import.meta.url), 'utf8');
  const job = name => workflow.split(/^  (?=[a-z][a-z-]*:)/m).find(block => block.startsWith(`${name}:\n`));
  for (const [name, title] of [['site', 'Build and test the public static site'], ['release', 'The release proofs']]) {
    const block = job(name);
    assert.ok(block.includes(`needs.changes.outputs.${name} == 'true'`));
    assert.ok(block.includes(`- name: ${title}\n`));
    assert.ok(block.includes(`run.py execute "$RUNNER_TEMP/ci-plan" ${name}`));
    assert.ok(block.includes('run: sh .github/actions/docs-only/python.sh'));
  }
  // Commands moved to the plan executor; preserve every previous obligation.
  for (const command of ["'site:build': ['npm', 'run', 'build']", "'site:test': ['npm', 'test']",
    "'site:ci': ['npm', 'run', 'test:ci']", "'release:test': ['python3', 'tools/release/test.py']"]) {
    assert.ok(runner.includes(command), `the plan executor retains ${command}`);
  }
  assert.ok(runner.includes("cwd='apps/site' if test.startswith('site:') else None"));
  for (const line of [
    'python3 --version',
    'x86_64) sum=df15fe60d3ff55bf9dcf25824b5572756bb8816ff93865a273d3301d7066a8b7 ;;',
    'aarch64) sum=578d9da1983463ffb0c8c98ab0da2f18177f44069328eb0af847860c1eb05c3e ;;',
    'echo "$sum  $RUNNER_TEMP/python.tar.gz" | sha256sum -c -',
    'export PATH="$python/bin:$PATH"',
  ]) assert.ok(fallback.includes(line), `CI retains ${line}`);
  assert.ok(fallback.includes('/20261026/cpython-3.13.18+20261026-$(uname -m)-unknown-linux-gnu-install_only_stripped.tar.gz'));
});
