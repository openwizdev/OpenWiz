// The browser proofs, 3 files at a time, longest first (#431, K14; spec
// #330: "3 files at a time, longest first … never 4"). With `--with-unit`
// (`npm test`, #1261), the unit files join the same pool, so the two that
// start Chromium no longer run before every browser file. Each file still
// runs in its own process, with the spec reporter and no time limit, as
// `node --test --test-force-exit` ran them one at a time. The order comes
// from file-times.tsv (each file's time in ms); a file it doesn't list still
// runs, last. The server and the fake are built once before the run, so each
// file's own build (support/rust.mjs) finds them current. On a pull request's
// first run against main, the soak skips itself (soak-skip.mjs). With
// `--only FILE...` (#432, the CI test selector) it runs just those files,
// each one it would otherwise run; the soak's coverage check then holds
// whenever the soak's file is among them, and nothing may skip otherwise.

import { globSync, readFileSync } from 'node:fs';
import { relative } from 'node:path';
import { run } from 'node:test';
import { spec } from 'node:test/reporters';

import { checkSkips, SOAK_ENV, SOAK_FILE, skipSoak } from './soak-skip.mjs';
import { WEB_DIR } from './support/paths.mjs';
import { buildBinaries } from './support/rust.mjs';

const CONCURRENCY = 3;
const TABLE = new URL('file-times.tsv', import.meta.url);
const ROW = /^(test\/browser\/(?:[A-Za-z0-9._-]+\/)*[A-Za-z0-9._-]+\.test\.mjs|test\/unit\/(?:[A-Za-z0-9._-]+\/)*[A-Za-z0-9._-]+\.test\.ts)\t(0|[1-9][0-9]*)$/;
const BROWSER = 'test/browser/**/*.test.mjs';
const UNIT = 'test/unit/**/*.test.ts';

/**
 * The run order of `files` (paths under `apps/web`): the ones `table` lists,
 * longest first, then the rest by name. Also the files it lacks (`missing`)
 * and its rows for files that aren't there (`stale`). A table that isn't
 * exactly the header `file\tms` and one row per file is refused.
 */
export function plan(files, table) {
  if (files.length === 0) throw new Error('run-browser: no test files');
  const ms = new Map();
  let header = false;
  for (const line of table.split('\n')) {
    if (line === '' || line.startsWith('#')) continue;
    if (!header) {
      if (line !== 'file\tms') throw new Error(`file-times.tsv: the header must be "file<TAB>ms", not ${JSON.stringify(line)}`);
      header = true;
      continue;
    }
    const m = ROW.exec(line);
    if (!m || m[1].split('/').some((part) => part === '..' || part === '.')) throw new Error(`file-times.tsv: not "test/browser/<name>.test.mjs<TAB><ms>" or "test/unit/<name>.test.ts<TAB><ms>": ${JSON.stringify(line)}`);
    if (ms.has(m[1])) throw new Error(`file-times.tsv: ${m[1]} is listed twice`);
    ms.set(m[1], Number(m[2]));
  }
  if (!header) throw new Error('file-times.tsv: no "file<TAB>ms" header');
  const unique = [...new Set(files)].sort();
  const timed = unique.filter((f) => ms.has(f)).sort((a, b) => ms.get(b) - ms.get(a) || (a < b ? -1 : 1));
  const missing = unique.filter((f) => !ms.has(f));
  const stale = [...ms.keys()].filter((f) => !unique.includes(f)).sort();
  return { order: [...timed, ...missing], missing, stale };
}

/** The files to run, under `apps/web`: the browser files, and with `withUnit` the unit files too (test:unit's glob). */
export function webFiles(withUnit) {
  return [...globSync(BROWSER, { cwd: WEB_DIR }), ...(withUnit ? globSync(UNIT, { cwd: WEB_DIR }) : [])];
}

/**
 * The runner's arguments: `--with-unit`, then optionally `--only FILE...`,
 * each FILE one of `files` (the files it would run), once. node --test's
 * options don't reach this runner: refuse them, never drop them.
 */
export function parseArgs(args, files = []) {
  const withUnit = args[0] === '--with-unit';
  const rest = withUnit ? args.slice(1) : args;
  if (rest.length === 0) return { withUnit };
  if (rest[0] !== '--only') throw new Error(`run-browser: takes no arguments but --with-unit and --only FILE..., got ${JSON.stringify(args)}`);
  const only = rest.slice(1);
  if (only.length === 0) throw new Error('run-browser: --only needs at least one file');
  for (const f of only) if (!files.includes(f)) throw new Error(`run-browser: --only ${JSON.stringify(f)} is not a file it runs`);
  if (new Set(only).size !== only.length) throw new Error('run-browser: --only names a file twice');
  return { withUnit, only: [...only].sort() };
}

/**
 * Whether this run owes the soak (#432): always, unless `--only` named the
 * files and left the soak's out. A full run whose file list lacks the soak
 * (a deleted or renamed file) still owes it, so the coverage check fails.
 */
export function soakSelected(args, order) {
  return args.only ? order.includes(SOAK_FILE) : true;
}

/**
 * node:test's run() options for `order`, given the runner's environment: the
 * test processes get it with the soak's flag set to 1 when this run skips the soak
 * (soak-skip.mjs), and without any inherited flag otherwise.
 */
export function runOptions(order, env) {
  const { [SOAK_ENV]: _inherited, ...rest } = env;
  return { files: order, cwd: WEB_DIR, concurrency: CONCURRENCY, forceExit: true, env: skipSoak(env) ? { ...rest, [SOAK_ENV]: '1' } : rest };
}

function main() {
  let args;
  const argv = process.argv.slice(2);
  try {
    args = parseArgs(argv, webFiles(argv[0] === '--with-unit'));
  } catch (e) {
    console.error(e.message);
    process.exit(2);
  }
  const files = args.only ?? webFiles(args.withUnit);
  if (args.only) console.error(`run-browser: the selected files only (#432): ${args.only.join(', ')}`);
  const { order, missing, stale } = plan(files, readFileSync(TABLE, 'utf8'));
  if (missing.length) console.error(`run-browser: not in test/file-times.tsv, so run last: ${missing.join(', ')}`);
  if (stale.length && !args.only) console.error(`run-browser: in test/file-times.tsv but not found: ${stale.join(', ')}`);
  buildBinaries();
  const options = runOptions(order, process.env);
  const skipping = options.env[SOAK_ENV] === '1';
  if (skipping) console.error('run-browser: a pull request\'s first run against main, so the soak skips itself');
  let success = false;
  const times = [];
  const seen = [];
  const stream = run(options);
  const note = (d) => {
    if (d.file) seen.push({ file: relative(WEB_DIR, d.file), name: d.name, nesting: d.nesting, skip: Boolean(d.skip) });
  };
  stream.on('test:pass', note);
  stream.on('test:fail', note);
  stream.on('test:summary', (summary) => {
    if (summary.file === undefined) success = summary.success;
    else times.push([relative(WEB_DIR, summary.file), Math.round(summary.duration_ms)]);
  });
  stream.on('end', () => {
    // Each file's time, longest first, in file-times.tsv's rows, to re-measure it from a run.
    console.log(`\nrun-browser: each file's time in this run (ms), longest first:\nfile\tms\n${times.sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map((t) => t.join('\t')).join('\n')}`);
    // The coverage check on what was reported: exactly the soak skipped on a skipping run; nothing skipped, and the soak run, otherwise.
    try {
      checkSkips(seen, skipping, soakSelected(args, order));
    } catch (e) {
      console.error(`run-browser: ${e.message}`);
      success = false;
    }
    process.exitCode = success ? 0 : 1;
  });
  stream.compose(spec).pipe(process.stdout);
}

if (import.meta.main) main();
