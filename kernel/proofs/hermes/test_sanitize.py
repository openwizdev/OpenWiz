import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sanitize  # noqa: E402

# Every value below is synthetic. Thread ids, home folders and credential shapes
# are built at run time so that no file holds one.
THREAD = 'thr' + '_a1b2C3-d4'
HOME, MAC = '/ho' + 'me/robin', '/Use' + 'rs/robin'
RAW = '\n'.join([
    f'thread {THREAD} started run-0123456789ab',
    f'log at {HOME}/.local/state/openwiz-local/run-0123456789ab.log',
    f'and {MAC}/work/site',
    'contact robin@example.com, commits by 1+robin@users.noreply.github.com',
    'token ' + 'ghs' + '_' + 'X' * 36 + ' and ' + 'github' + '_pat_' + 'Y' * 30,
    'key ' + 'sk' + '-ant-' + 'Z' * 20,
    'machine robins-laptop.example.lan said hi',
    'Robin wrote: keep it small',
])


class Sanitize(unittest.TestCase):
    def test_live_identifiers_and_credentials_are_replaced(self):
        out = sanitize.sanitize_text(RAW, literals=['robins-laptop.example.lan'])
        for i, leaked in enumerate([THREAD, 'run-0123456789ab', HOME, MAC,
                       'robin@example.com', 'ghs' + '_', 'github' + '_pat', 'sk' + '-ant',
                       'robins-laptop.example.lan']):
            self.assertFalse(leaked in out, f'live value {i} still present')
        # Public forms survive: noreply commit identities and ordinary words.
        self.assertIn('1+robin@users.noreply.github.com', out)
        self.assertIn('[thread]', out)
        self.assertIn('run-000000000001', out)
        self.assertIn('~/.local/state/openwiz-local/run-000000000001.log', out)

    def test_same_run_id_maps_to_the_same_placeholder(self):
        out = sanitize.sanitize_text('run-aaaaaaaaaaaa run-bbbbbbbbbbbb run-aaaaaaaaaaaa')
        self.assertEqual(out, 'run-000000000001 run-000000000002 run-000000000001')

    def test_cli_refuses_without_literals_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d, 'in'), Path(d, 'out')
            src.mkdir()
            (src / 'log.txt').write_text(RAW)
            r = subprocess.run([sys.executable, '-I', str(HERE / 'sanitize.py'), str(src), str(dst)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertFalse(dst.exists())

    def test_cli_removes_output_when_the_privacy_check_refuses(self):
        # catches: a private literal the text pass can't reach (a file name) reaching OUT_DIR
        with tempfile.TemporaryDirectory() as d:
            src, dst, lit = Path(d, 'in'), Path(d, 'out'), Path(d, 'literals')
            src.mkdir()
            (src / 'robins-laptop.txt').write_text('hello')
            lit.write_text('robins-laptop\n')
            r = subprocess.run([sys.executable, '-I', str(HERE / 'sanitize.py'), str(src), str(dst),
                                '--literals', str(lit)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertFalse(dst.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
