#!/usr/bin/env python3
"""WR10: gather the real War room sources into one pinned WR2 selection.

A local bare origin holds a synthetic `board` branch (graph, history,
credits.jsonl) and a synthetic `ci-benchmarks` branch; a synthetic gh answers
WR8's reads (fixtures/activity/fake_gh.py); journeys, their cohort and an
answer-time projection are fixture artifacts. No network, no live read.
"""
import base64
import contextlib
import copy
import functools
import hashlib
import html
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
FIX = HERE / 'fixtures'
REPO = 'synthetic-owner/work'
RUN = 'https://github.com/synthetic-owner/work/actions/runs/9001'
STARTED, ENDED = '2030-01-02T12:29:00Z', '2030-01-02T12:30:00Z'
PUBLISH_AT = '2030-01-02T12:33:00Z'
BOARD_AT, BENCH_AT = '2030-01-02T12:20:00Z', '2030-01-02T12:10:00Z'
LISTED = 'repos/synthetic-owner/work/actions/workflows/ci.yml/runs?'
ACTIVE = ('in_progress', 'queued', 'waiting', 'pending', 'requested')
STATUS = LISTED + 'status=%s&per_page=100&page=1'
DONE = LISTED + 'created=2030-01-02T00:00:00Z..' + ENDED + '&status=completed&per_page=100&page=1'
GATHERED = {'activity', 'board', 'ci_bench', 'journey', 'cost', 'credits', 'answer_time', 'rework'}
# #2565: the shape of the real gathered page of 2026-11-13, counts only: per card, its metrics,
# each incomplete metric's prerequisites and each measured metric's evidence links. Real chromium
# measured that page at 57,625 CSS px (1200 wide) and 49,909 (400 wide, drawn 2x). Its journey
# card's 8 metrics are left out: the fixture's journey card has none to copy.
REAL_SCALE = {'activity': (12, 0, 18), 'board': (8, 1, 1), 'ci_bench': (7, 0, 1),
              'cost': (74, 5, 1), 'credits': (25, 1, 1), 'rework': (7, 6, 48)}


def real_scale(providers):
    """The gathered fixture's providers grown to REAL_SCALE with synthetic copies."""
    providers, n = copy.deepcopy(providers), 0
    for p in providers:
        if p['slot'] not in REAL_SCALE or not p['metrics']:
            continue
        count, prerequisites, links = REAL_SCALE[p['slot']]
        base = list(p['metrics'])
        while len(p['metrics']) < count:
            k = len(p['metrics'])
            m = copy.deepcopy(base[k % len(base)])
            m['id'] += '-copy-%d' % k
            m['label'] += ' (copy %d)' % k
            p['metrics'].append(m)
        for m in p['metrics']:
            if m['state'] != 'known':
                m['prerequisites'] += ['Synthetic prerequisite %d' % i for i in range(len(m['prerequisites']), prerequisites)]
            while m['evidence'] and len(m['evidence']) < links:
                n += 1
                m['evidence'].append('https://github.com/synthetic-owner/work/issues/%d' % (900000 + n))
    return providers


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(HERE))
import sources  # noqa: E402
import suite  # noqa: E402
import answer_time  # noqa: E402
import rework  # noqa: E402
WR8 = load('wr8_fixture', HERE / 'test_activity.py')


def publish_module():
    import publish
    return publish


@functools.lru_cache(maxsize=None)
def gatherer():
    return load('gather', HERE / 'gather.py')


def probed(page, width, script):
    """What `script` (a JS expression, run on load) finds in `page` as real chromium lays it out at `width`."""
    probe = "<script>addEventListener('load',()=>{document.body.dataset.probe=JSON.stringify(%s)})</script></body>"
    with tempfile.TemporaryDirectory(prefix='war-room-probe-') as d:
        path = Path(d) / 'page.html'
        path.write_text(page.replace('</body>', probe % script), encoding='utf-8')
        dom = subprocess.run([publish_module().chromium(), '--headless=new', '--no-sandbox', '--disable-gpu',
                              '--user-data-dir=' + d + '/chr', '--window-size=%d,800' % width,
                              '--dump-dom', path.as_uri()], check=True, capture_output=True, text=True, timeout=90).stdout
    return json.loads(html.unescape(re.search(r'data-probe="([^"]*)"', dom).group(1)))


def visible_cards(page, phone):
    """Each value card's text as real chromium shows it in the drawn picture (innerText skips hidden rows)."""
    return probed(publish_module().drawable(page, phone), 400 if phone else 1200,
                  "[...document.querySelectorAll('article.metric')].map(a=>a.innerText)")


# #2586: the label of the page's last card, so a picture whose lower part was never painted
# (a correctly sized PNG, blank from some height down) is told from a whole one.
MARKER = 'Synthetic bottom-page marker'


def marked(providers):
    """The providers with the last card the page draws (last group, last provider, last metric) labelled MARKER."""
    order = [d['slot'] for d in suite.PROVIDERS]
    last = max(((suite.GROUPS.index(m['group']), order.index(p['slot']), i), m)
               for p in providers for i, m in enumerate(p['metrics']))[1]
    last['label'] = MARKER
    return providers


def marker_pixels(page, png, phone):
    """How many of the picture's pixels inside the marker's heading have its text and its card's colour."""
    found = probed(publish_module().drawable(page, phone), 400 if phone else 1200, (
        "(()=>{const h=[...document.querySelectorAll('h4')].filter(e=>e.textContent===%s);"
        "if(h.length!==1)return null;const r=h[0].getBoundingClientRect();"
        "return {box:[r.left,r.top+scrollY,r.width,r.height],text:getComputedStyle(h[0]).color,"
        "card:getComputedStyle(h[0].closest('article')).backgroundColor}})()") % json.dumps(MARKER))
    assert found, 'the marker is not on the drawn page once'
    scale = 2 if phone else 1
    x, y, w, h = (round(v * scale) for v in found['box'])
    # The picture, decoded by chromium: only the marker's box is copied to a canvas.
    count = ("(()=>{const c=document.createElement('canvas');c.width=%d;c.height=%d;const g=c.getContext('2d');"
             "const i=document.images[0];g.drawImage(i,%d,%d,%d,%d,0,0,%d,%d);i.remove();"
             "const d=g.getImageData(0,0,%d,%d).data;const near=s=>{const [r,G,b]=s.match(/[0-9]+/g).map(Number);"
             "let n=0;for(let k=0;k<d.length;k+=4)n+=Math.abs(d[k]-r)+Math.abs(d[k+1]-G)+Math.abs(d[k+2]-b)<=12;return n};"
             "return {size:[i.naturalWidth,i.naturalHeight],text:near(%s),card:near(%s)}})()") % (
        w, h, x, y, w, h, w, h, w, h, json.dumps(found['text']), json.dumps(found['card']))
    image = '<html><body><img src="data:image/png;base64,%s"></body></html>' % base64.b64encode(png).decode()
    return probed(image, 400, count)


def git(cwd, *args, env=None):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True,
                          env=env).stdout


class Gather(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='war-room-gather-'))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.origin = self.tmp / 'origin.git'
        git(self.tmp, 'init', '-q', '--bare', str(self.origin))
        graph = json.loads((FIX / 'page-history/board-graph.json').read_text())
        graph['repo'] = REPO
        self.branch('board', BOARD_AT, {
            'graph.json': json.dumps(graph, indent=2) + '\n',
            'history.jsonl': (FIX / 'gather/history.jsonl').read_text(),
            'credits.jsonl': (FIX / 'gather/credits.jsonl').read_text(),
            'README.md': 'synthetic board\n'})
        point = (FIX / 'cost/ci/point.json').read_text()
        older = json.loads(point)
        older.update(since='2029-12-31T08:00:00Z', until='2030-01-01T08:00:00Z', merged_prs=5,
                     merged_per_hour=0.208333)
        self.branch('ci-benchmarks', BENCH_AT, {'windows/aaaa/point.json': point,
                                                'windows/bbbb/point.json': json.dumps(older)})
        self.refs_before = self.refs()
        # WR8's synthetic gh, answering WR8's own fixture reads.
        bin_dir = self.tmp / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'gh').symlink_to(FIX / 'activity/fake_gh.py')
        self.answers = self.tmp / 'gh.json'
        self.answer(WR8.fixture())
        self.env = {'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'], 'WR8_FIXTURE': str(self.answers)}
        # WR5's own projection of its synthetic pairs: the answer-time artifact.
        pairs = json.loads((FIX / 'answer-time/pairs.json').read_text())['projection']
        facts = json.dumps(pairs, sort_keys=True).encode()
        provider = answer_time.project(
            pairs['sample_at'], source={'path': 'answer-time/pairs.json', 'schema': 'openwiz.war-room.answer-time.synthetic',
                                        'sha256': hashlib.sha256(facts).hexdigest()},
            window=pairs['window'], observed_at=pairs['observed_at'], cohort=pairs['cohort'],
            requests=pairs['requests'], dispositions=pairs['dispositions'], expected=pairs['expected'],
            history=pairs['history'])
        self.answer_time = self.tmp / 'answer-time.json'
        self.answer_time.write_text(json.dumps(provider))
        self.journeys = FIX / 'rework/journeys.json'
        self.cohort = FIX / 'gather/cohort.json'

    def answer(self, answers, current=None):
        """WR8's synthetic gh answers, with ci.yml's runs also listed by status and the day's completed cohort."""
        listed = answers[WR8.RUNS]['workflow_runs']
        current = {s: [r for r in listed if r['status'] == s] for s in ACTIVE} if current is None else current
        for status in ACTIVE:
            runs = current.get(status, [])
            answers[STATUS % status] = {'total_count': len(runs), 'workflow_runs': runs}
        done = current.get('completed', [])
        answers[DONE] = {'total_count': len(done), 'workflow_runs': done}
        self.answers.write_text(json.dumps(answers))
        return answers

    def branch(self, name, at, files):
        work = Path(tempfile.mkdtemp(prefix='seed-', dir=self.tmp))
        git(self.tmp, 'init', '-q', str(work))
        for path, text in files.items():
            (work / path).parent.mkdir(parents=True, exist_ok=True)
            (work / path).write_text(text)
        stamp = dict(os.environ, GIT_AUTHOR_DATE=at, GIT_COMMITTER_DATE=at)
        git(work, 'add', '-A')
        git(work, '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
            'commit', '-q', '-m', 'synthetic ' + name, env=stamp)
        git(work, 'push', '-q', '-f', str(self.origin), 'HEAD:refs/heads/' + name)
        return git(work, 'rev-parse', 'HEAD').strip()

    def refs(self):
        return git(self.origin, 'for-each-ref', '--format=%(objectname) %(refname)')

    def gather(self, out=None, **overrides):
        out = self.tmp / 'out' if out is None else out
        clock = iter([STARTED, ENDED])
        args = dict(remote=str(self.origin), repo=REPO, run_url=RUN, clock=lambda: next(clock),
                    pools=WR8.POOLS, journeys=self.journeys, cohort=self.cohort, answer_time=self.answer_time)
        args.update(overrides)
        with patch.dict(os.environ, self.env):
            gatherer().gather(out, **args)
        return out / 'root', json.loads((out / 'selection.json').read_text())

    def publish(self, root, selection_path):
        fakes = FIX / 'publish'
        env = dict(os.environ, PATH=str(fakes) + os.pathsep + os.environ['PATH'],
                   FAKE_CHROMIUM_LOG=str(self.tmp / 'chromium.log'), FAKE_GH_LOG=str(self.tmp / 'gh.log'))
        result = subprocess.run([sys.executable, '-I', str(HERE / 'publish.py'), 'publish', '--remote', str(self.origin),
                                 '--at', PUBLISH_AT, '--source-root', str(root), '--selection', str(selection_path)],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        sample = subprocess.run(['git', '-C', str(self.origin), 'show',
                                 'refs/heads/war-room:samples/2030-01-02T12-30-00Z.json'],
                                check=True, capture_output=True).stdout
        record = suite.loads(sample.decode())
        return {p['slot']: p for p in record['providers']}

    def values(self, provider):
        return {m['id']: m['value'] for m in provider['metrics'] if m['value'] is not None}

    def test_gather_writes_a_selection_sources_select_accepts(self):
        root, selection = self.gather()
        self.assertEqual({s['slot'] for s in selection}, GATHERED)
        for s in selection:
            with self.subTest(s['slot']):
                # Pinned by sha256 of the gathered bytes and an observed time no later than the read.
                self.assertEqual(hashlib.sha256((root / s['path']).read_bytes()).hexdigest(), s['sha256'])
                self.assertLessEqual(s['observed_at'], ENDED)
                self.assertTrue(s['evidence'])
        by_slot = {s['slot']: s for s in selection}
        self.assertEqual(by_slot['credits']['kind'], 'credits')
        self.assertEqual(by_slot['ci_bench']['kind'], 'ci_bench')
        self.assertEqual(by_slot['journey']['kind'], 'journey')
        self.assertEqual(by_slot['board']['observed_at'], BOARD_AT)
        self.assertEqual(by_slot['credits']['observed_at'], BOARD_AT)
        self.assertEqual(by_slot['ci_bench']['observed_at'], BENCH_AT)
        self.assertEqual(by_slot['activity']['observed_at'], ENDED)
        self.assertEqual(by_slot['rework']['observed_at'], '2030-01-02T12:00:00Z')
        self.assertRegex(by_slot['credits']['evidence'][0], r'^https://github\.com/synthetic-owner/work/commit/[0-9a-f]{40}$')
        # The latest completed CI bench window, not an older one.
        self.assertEqual(json.loads((root / by_slot['ci_bench']['path']).read_text())['until'], '2030-01-02T08:00:00Z')
        providers = sources.select(root, selection, ENDED)
        for s, p in zip(selection, providers):
            with self.subTest(s['slot']):
                self.assertNotEqual(p, sources._failed(s['slot'], None, ENDED))
        # board and ci-benchmarks are only read: every ref of the origin is unchanged.
        self.assertEqual(self.refs(), self.refs_before)

    def test_publish_shows_measured_values_with_provenance(self):
        root, selection = self.gather()
        cards = self.publish(root, self.tmp / 'out/selection.json')
        board = self.values(cards['board'])
        self.assertEqual((board['open-approved'], board['can-start'], board['ready-stock'],
                          board['builders-running'], board['startable-percent']), (6, 2, 2, 0, 33))
        self.assertEqual(sorted(self.values(cards['credits']).values()), [15, 30])
        self.assertEqual(self.values(cards['ci_bench'])['merged'], 2)
        self.assertEqual(self.values(cards['activity'])['ci-queued-ubuntu-24.04'], 1)
        self.assertEqual(self.values(cards['rework'])['review-changes-share'], 0.5)
        self.assertEqual(self.values(cards['answer_time'])['answer-coverage'], 1 / 3)
        self.assertEqual(self.values(cards['cost'])['ci-estimate'], 0.2)
        for slot in GATHERED - {'journey'}:
            with self.subTest(slot):
                shown = [m for m in cards[slot]['metrics'] if m['value'] is not None]
                self.assertTrue(shown, slot + ' shows no measured value')
                for m in shown:
                    self.assertRegex(m['source']['sha256'], '^[0-9a-f]{64}$')
                    self.assertTrue(m['evidence'] and m['observed_at'] and m['window'])
        # A point the source cannot divide stays Unknown with its reason, never zero.
        fed = next(m for m in cards['board']['metrics'] if m['id'] == 'fed-ratio')
        self.assertIsNone(fed['value'])
        self.assertTrue(any('builders running' in p for p in fed['prerequisites']))

    def test_the_full_gathered_selection_publishes_with_real_chromium(self):
        # #2432 R1: the whole gathered page, drawn by the real chromium at both widths, publishes;
        # the fake chromium's fixed height hid that it is far taller than the old 8,000 px cap.
        root, selection = self.gather()
        self.assertTrue(publish_module().chromium(), 'the real chromium is required')
        env = dict(os.environ)
        env.pop('FAKE_CHROMIUM_HEIGHT', None)
        result = subprocess.run([sys.executable, '-I', str(HERE / 'publish.py'), 'publish', '--remote', str(self.origin),
                                 '--at', PUBLISH_AT, '--source-root', str(root),
                                 '--selection', str(self.tmp / 'out/selection.json')],
                                env=env, capture_output=True, text=True, timeout=600)
        self.assertEqual(result.returncode, 0, result.stderr)
        files = git(self.origin, 'ls-tree', '-r', '--name-only', 'refs/heads/war-room').split()
        self.assertEqual(sorted(files), ['README.md', 'samples/2030-01-02T12-30-00Z.json',
                                         'war-room-phone.png', 'war-room.png'])
        sizes = {}
        for name in ('war-room.png', 'war-room-phone.png'):
            data = subprocess.run(['git', '-C', str(self.origin), 'show', 'refs/heads/war-room:' + name],
                                  check=True, capture_output=True).stdout
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            sizes[name] = struct.unpack('>II', data[16:24])
        self.assertEqual(sizes['war-room.png'][0], 1200)
        self.assertEqual(sizes['war-room-phone.png'][0], 800)
        self.assertGreater(sizes['war-room.png'][1], 8000, 'the full page, not a clipped one')
        self.assertGreater(sizes['war-room-phone.png'][1], 2 * 8000)
        # Every gathered card, with measured values, is on the page that was drawn: all 65 metrics the
        # review counted for this fixture. The board shows its six counts and the startable percent;
        # the fed ratio is undefined with no builders running.
        readme = git(self.origin, 'show', 'refs/heads/war-room:README.md')
        self.assertIn('| Board | partial | 7 of 8 |', readme)
        rows = {}
        for line in readme.splitlines():
            cells = [c.strip() for c in line.strip('|').split('|')]
            if len(cells) == 3 and ' of ' in cells[2]:
                rows[cells[0]] = [int(n) for n in cells[2].split(' of ')]
        cards = ('Board', 'Credits', 'CI bench', 'Current activity', 'Rework rate', 'Orchestrator answer time',
                 'All-in cost per merged PR')
        self.assertTrue(all(rows[card][0] > 0 for card in cards), rows)
        self.assertEqual(sum(rows[card][1] for card in cards), 65)

    def test_each_picture_card_shows_what_tells_it_apart(self):
        # #2565 R1: cards can share a label (a credit drop per interval; CI median and p90), so
        # each picture card shows its window, freshness, statistic and dimensions; its long
        # provenance and evidence links stay in the published sample.
        point = json.loads((FIX / 'cost/ci/point.json').read_text())
        point['code_runs'] = {'rule': 'synthetic successful code runs', 'runs': 2, 'robot_seconds': 240,
                              'robot_minutes_per_run': 2, 'prs_per_hour': 150,
                              'categories': dict.fromkeys(('web', 'setup', 'rust', 'build', 'skills'), 0),
                              'split': {'waiting': 1, 'setup': 1, 'running': 1},
                              'queued_to_done': {'median': 7, 'p90': 9, 'max': 9}}
        self.branch('ci-benchmarks', BENCH_AT, {'windows/aaaa/point.json': json.dumps(point)})
        root, _ = self.gather()
        read = publish_module().selection_reader(root, self.tmp / 'out/selection.json')
        page = publish_module().tick(self.tmp / 'private' / 'history', PUBLISH_AT, read).read_text(encoding='utf-8')
        record = suite.load(next((self.tmp / 'private' / 'history' / 'samples').glob('*.json')))
        labels = {}
        for p in record['providers']:
            for m in p['metrics']:
                labels.setdefault((p['slot'], m['label']), []).append(m)
        shared = {slot for (slot, _), ms in labels.items() if len(ms) > 1}
        self.assertLessEqual({'credits', 'ci_bench'}, shared, 'cards that share a label: credit drops, CI median and p90')
        # The page shows the cards group by group; the same order, rebuilt from the record.
        metrics = [m for g in suite.GROUPS for p, d in zip(record['providers'], suite.PROVIDERS)
                   if g in d['groups'] for m in p['metrics'] if m['group'] == g]
        for phone in (False, True):
            cards = visible_cards(page, phone)
            self.assertEqual(len(cards), len(metrics))
            for m, card in zip(metrics, cards):
                with self.subTest(phone=phone, metric=m['id']):
                    self.assertIn(m['label'], card)
                    if m['window'] is not None:
                        self.assertIn(m['window']['since'], card)
                        self.assertIn(m['window']['until'], card)
                    self.assertIn(m['statistic'], card)
                    self.assertIn(m['freshness'], card)
                    for v in m['dimensions'].values():
                        if v is not None:
                            self.assertIn(str(v), card)
                    if m['source'] is not None:
                        self.assertNotIn(m['source']['sha256'], card)
                    self.assertNotIn('source 1', card)
            for (slot, label), ms in labels.items():
                shown = [cards[metrics.index(m)] for m in ms]
                self.assertEqual(len(set(shown)), len(shown), (slot, label))

    def test_a_real_scale_gathered_page_draws_with_real_chromium(self):
        # #2565: the real gathered page grew past the bound (57,625 CSS px; the phone picture 99,818
        # device px), so every main publish refused it. The same page shape, synthetic, must draw.
        root, _ = self.gather()
        read = publish_module().selection_reader(root, self.tmp / 'out/selection.json')
        out = self.tmp / 'pictures'
        out.mkdir()
        page = publish_module().render(out, self.tmp / 'private' / 'history', PUBLISH_AT,
                                       lambda at, previous: marked(real_scale(read(at, previous))))
        record = suite.load(next((self.tmp / 'private' / 'history' / 'samples').glob('*.json')))
        self.assertEqual(sum(len(p['metrics']) for p in record['providers'] if p['slot'] in REAL_SCALE), 133)
        for name, width, phone in (('war-room.png', 1200, False), ('war-room-phone.png', 800, True)):
            with self.subTest(name):
                data = (out / name).read_bytes()
                self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                drawn, height = struct.unpack('>II', data[16:24])
                self.assertEqual(drawn, width)
                self.assertLessEqual(height, publish_module().MAX_HEIGHT)
                # #2586: and painted to the bottom: the last card's heading shows its text on its card.
                pixels = marker_pixels(page, data, phone)
                self.assertEqual(pixels['size'], [drawn, height])
                self.assertGreater(pixels['text'], 50, 'the marker text is not painted')
                self.assertGreater(pixels['card'], 500, "the marker's card is not painted")

    def test_a_removed_or_unreadable_source_greys_only_its_own_card(self):
        git(self.origin, 'update-ref', '-d', 'refs/heads/ci-benchmarks')
        self.branch('board', BOARD_AT, {'history.jsonl': (FIX / 'gather/history.jsonl').read_text(),
                                        'credits.jsonl': 'not a credit sample\n'})
        root, selection = self.gather()
        cards = self.publish(root, self.tmp / 'out/selection.json')
        for slot, source, prerequisite in (
                ('ci_bench', 'ci-benchmarks', 'tools/ci-bench/daily.sh'),
                ('credits', 'credits.jsonl', 'credit sampler')):
            with self.subTest(slot):
                self.assertEqual(cards[slot]['state'], 'unavailable')
                reason = ' '.join(cards[slot]['prerequisites'])
                self.assertIn(source, reason)
                self.assertIn(prerequisite, reason)
        for slot in ('board', 'activity', 'rework', 'answer_time'):
            with self.subTest(slot):
                self.assertTrue(self.values(cards[slot]), slot + ' lost its values')
        # Without a graph on the branch, the ratios name it as their prerequisite.
        ratio = next(m for m in cards['board']['metrics'] if m['id'] == 'startable-percent')
        self.assertIsNone(ratio['value'])
        self.assertTrue(any('graph.json' in p for p in ratio['prerequisites']))

    def test_without_journeys_or_answer_records_each_card_names_its_prerequisite(self):
        # No fake gh answers journey reads: collection fails, and only those cards grey.
        root, selection = self.gather(journeys=None, cohort=None, answer_time=None)
        cards = {p['slot']: p for p in sources.select(root, selection, ENDED)}
        self.assertEqual(cards['answer_time'], answer_time.unavailable())
        for slot in ('journey', 'rework'):
            with self.subTest(slot):
                self.assertEqual(cards[slot]['state'], 'unavailable')
                self.assertIn('journey.py collect', ' '.join(cards[slot]['prerequisites']))
        self.assertTrue(self.values(cards['board']))

    def test_a_planted_secret_turns_the_privacy_scan_red(self):
        provider = json.loads(self.answer_time.read_text())
        for planted in ('ghp_' + 'A' * 36, 'thr_' + 'synthetic9'):
            with self.subTest(planted[:4]):
                provider['prerequisites'] = provider['prerequisites'] + ['planted ' + planted]
                self.answer_time.write_text(json.dumps(provider))
                out = self.tmp / ('planted-' + planted[:3])
                with self.assertRaises(gatherer().Fail) as refused, contextlib.redirect_stdout(io.StringIO()):
                    self.gather(out)
                self.assertIn('privacy scan', str(refused.exception))
                self.assertNotIn(planted, str(refused.exception))
                self.assertFalse((out / 'selection.json').exists(), 'a refused gather selects nothing')
                provider['prerequisites'] = provider['prerequisites'][:-1]

    def test_a_long_run_history_keeps_the_current_ci_counts(self):
        # R2: ci.yml's whole history is over the API's 1000-item limit; the current runs are few.
        answers = WR8.fixture()
        old = {'id': 7, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'success',
               'created_at': '2029-06-01T10:00:00Z'}
        answers[WR8.RUNS] = {'total_count': 3315, 'workflow_runs': [old] * 100}
        run = WR8.fixture()[WR8.RUNS]['workflow_runs'][0]
        self.answer(answers, current={'in_progress': [run]})
        root, selection = self.gather()
        cards = {p['slot']: p for p in sources.select(root, selection, ENDED)}
        self.assertEqual({k: v for k, v in self.values(cards['activity']).items() if k.startswith('ci-')},
                         {'ci-running-ubuntu-24.04': 1, 'ci-queued-ubuntu-24.04': 1,
                          'ci-running-ubuntu-slim': 0, 'ci-queued-ubuntu-slim': 1, 'ci-cost-today-estimate': 0})

    def test_an_inconsistent_status_listing_gives_no_ci_counts(self):
        # Fail closed: a run in two status listings, or listed under a status it does not have, is no count.
        run = WR8.fixture()[WR8.RUNS]['workflow_runs'][0]
        for name, current in (('twice', {'in_progress': [run], 'queued': [run]}),
                              ('mislabelled', {'queued': [run]})):
            with self.subTest(name):
                self.answer(WR8.fixture(), current=current)
                root, selection = self.gather(self.tmp / name)
                cards = {p['slot']: p for p in sources.select(root, selection, ENDED)}
                ci = [m for m in cards['activity']['metrics'] if m['id'].startswith('ci-running')
                      or m['id'].startswith('ci-queued')]
                self.assertEqual(len(ci), 4)
                self.assertTrue(all(m['value'] is None for m in ci), name)

    def test_an_escaped_secret_in_a_valid_journey_refuses_the_gather(self):
        # R3: JSON escapes hide a credential from a byte scan; the native journey reader still accepts it.
        doc = json.loads(self.journeys.read_text())
        for planted, escaped in (('ghp_' + 'A' * 36, '\\u0067hp_' + 'A' * 36),
                                 ('github_pat_' + 'B' * 22, 'github\\u005fpat_' + 'B' * 22)):
            with self.subTest(planted[:4]):
                marker = 'synthetic-escape-marker'
                doc['sources']['s1'] = doc['sources']['s1'].split('-x-')[0] + '-x-' + marker
                wire = json.dumps(doc, indent=2).replace(marker, escaped)
                self.assertNotIn(planted, wire)
                decoded = json.loads(wire)
                self.assertIn(planted, decoded['sources']['s1'])
                gatherer()  # loads the journey reader
                rework.J.validate(decoded)  # a valid native artifact
                journeys = self.tmp / ('escaped-' + planted[:3] + '.json')
                journeys.write_text(wire)
                out = self.tmp / ('escaped-' + planted[:3])
                with self.assertRaises(gatherer().Fail) as refused:
                    self.gather(out, journeys=journeys)
                self.assertIn('privacy scan', str(refused.exception))
                self.assertNotIn(planted, str(refused.exception))
                self.assertFalse(out.exists(), 'a refused gather writes nothing')


if __name__ == '__main__':
    unittest.main()
