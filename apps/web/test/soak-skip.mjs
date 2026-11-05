// The soak off the PR path (#1261, folding K13 #430). Only on a pull
// request's first run against main (GITHUB_EVENT_NAME exactly
// `pull_request`, GITHUB_RUN_ATTEMPT exactly `1`, GITHUB_BASE_REF exactly
// `main`) does the runner set OPENWIZ_SKIP_SOAK=1 for the test processes, and
// the soak, the one test that reads it, skips itself. Anything else, including
// a rerun, a release branch's pull request, a missing or odd value, a push to
// main, the nightly run and a local `npm test`, runs it. The Sol 3 test in the
// same file always runs. No name pattern is used, so no other test, nested or
// not, can be skipped by sharing the soak's title (review R1).

export const SOAK_FILE = 'test/browser/v7-soak.test.mjs';
export const SOAK_ENV = 'OPENWIZ_SKIP_SOAK';
const SOAK_TITLE = /^soak: /;

/** Whether this run skips the soak: a pull request's first attempt against main, and nothing else. */
export function skipSoak(env) {
  return env.GITHUB_EVENT_NAME === 'pull_request' && env.GITHUB_RUN_ATTEMPT === '1' && env.GITHUB_BASE_REF === 'main';
}

/**
 * The coverage check, on every test and suite a run reported (`{ file, name,
 * nesting, skip }`, `file` under `apps/web`). A skipping run must have
 * skipped exactly one, the soak at the top of its file; any other run must
 * have skipped none and run the soak once. A run whose selection (#432,
 * `--only`) left the soak's file out (`soakSelected` false) must have
 * skipped none and reported no soak at all.
 */
export function checkSkips(tests, skipping, soakSelected = true) {
  const skipped = tests.filter((t) => t.skip);
  const isSoak = (t) => t.file === SOAK_FILE && t.nesting === 0 && SOAK_TITLE.test(t.name);
  const soaks = tests.filter(isSoak);
  const list = (xs) => xs.map((t) => `${t.file}: ${JSON.stringify(t.name)} (nesting ${t.nesting})`).join('; ') || 'none';
  if (!soakSelected) {
    if (skipped.length === 0 && soaks.length === 0) return;
    throw new Error(`soak skip: a run without the soak's file must skip nothing and run no soak; skipped: ${list(skipped)}; soak runs reported: ${soaks.length}`);
  }
  const ok = skipping
    ? skipped.length === 1 && isSoak(skipped[0]) && soaks.length === 1
    : skipped.length === 0 && soaks.length === 1;
  if (!ok) {
    throw new Error(`soak skip: a ${skipping ? 'skipping' : 'full'} run must ${skipping ? 'skip exactly the soak' : 'skip nothing and run the soak once'}; skipped: ${list(skipped)}; soak runs reported: ${soaks.length}`);
  }
}
