#!/usr/bin/env python3
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_glibc

PASS_OUTPUT = """\
Version symbols section '.gnu.version' contains 4 entries:
 Addr: 0x0000000000001000  Offset: 0x00001000  Link: 5 (.dynsym)
  000:   0 (*local*)       2 (GLIBC_2.17)    3 (GLIBC_2.34)    1 (*global*)

Version needs section '.gnu.version_r' contains 2 entries:
 Addr: 0x0000000000002000  Offset: 0x00002000  Link: 6 (.dynstr)
  000000: Version: 1  File: ld-linux-aarch64.so.1  Cnt: 1
  0x0010:   Name: GLIBC_2.17  Flags: none  Version: 4
  0x0020: Version: 1  File: libc.so.6  Cnt: 4
  0x0030:   Name: GLIBC_2.28  Flags: none  Version: 5
  0x0040:   Name: GLIBC_2.32  Flags: none  Version: 6
  0x0050:   Name: GLIBC_2.34  Flags: none  Version: 3
  0x0060:   Name: GLIBC_2.17  Flags: none  Version: 2
"""

HARD_FAIL_OUTPUT = """\
Version needs section '.gnu.version_r' contains 1 entry:
 Addr: 0x0000000000002000  Offset: 0x00002000  Link: 6 (.dynstr)
  000000: Version: 1  File: libc.so.6  Cnt: 3
  0x0010:   Name: GLIBC_2.17  Flags: none  Version: 2
  0x0020:   Name: GLIBC_2.34  Flags: none  Version: 3
  0x0030:   Name: GLIBC_2.39  Flags: none  Version: 4
"""

WEAK_FAIL_OUTPUT = """\
Version needs section '.gnu.version_r' contains 1 entry:
 Addr: 0x0000000000002000  Offset: 0x00002000  Link: 6 (.dynstr)
  000000: Version: 1  File: libc.so.6  Cnt: 2
  0x0010:   Name: GLIBC_2.17  Flags: none  Version: 2
  0x0020:   Name: GLIBC_2.39  Flags: WEAK  Version: 4
"""

PATCH_FAIL_OUTPUT = """\
Version needs section '.gnu.version_r' contains 1 entry:
 Addr: 0x0000000000002000  Offset: 0x00002000  Link: 6 (.dynstr)
  000000: Version: 1  File: libc.so.6  Cnt: 2
  0x0010:   Name: GLIBC_2.17  Flags: none  Version: 2
  0x0020:   Name: GLIBC_2.34.1  Flags: none  Version: 3
"""

PRIVATE_OUTPUT = """\
Version needs section '.gnu.version_r' contains 1 entry:
 Addr: 0x0000000000002000  Offset: 0x00002000  Link: 6 (.dynstr)
  000000: Version: 1  File: libc.so.6  Cnt: 2
  0x0010:   Name: GLIBC_2.17  Flags: none  Version: 2
  0x0020:   Name: GLIBC_PRIVATE  Flags: none  Version: 3
"""

NON_GLIBC_ONLY_OUTPUT = """\
Version needs section '.gnu.version_r' contains 1 entry:
 Addr: 0x0000000000002000  Offset: 0x00002000  Link: 6 (.dynstr)
  000000: Version: 1  File: libz.so.1  Cnt: 1
  0x0010:   Name: ZLIB_1.2.2  Flags: none  Version: 2
"""

UNPARSEABLE_ENTRY_OUTPUT = """\
Version needs section '.gnu.version_r' contains 1 entry:
 Addr: 0x0000000000002000  Offset: 0x00002000  Link: 6 (.dynstr)
  000000: Version: 1  File: libc.so.6  Cnt: 1
  0x0010:   Name: GLIBC_2.34  BrokenFormat
"""


class GlibcCheckTest(unittest.TestCase):
    def test_accepts_versions_at_or_below_ceiling(self):
        name, ver, flags = check_glibc.check_verneed(PASS_OUTPUT, '2.34')
        self.assertEqual((name, ver, flags), ('GLIBC_2.34', (2, 34), 'none'))

    def test_rejects_hard_verneed_above_ceiling(self):
        with self.assertRaises(check_glibc.CheckError) as ctx:
            check_glibc.check_verneed(HARD_FAIL_OUTPUT, '2.34')
        self.assertIn('GLIBC_2.39 (Flags: none)', str(ctx.exception))

    def test_rejects_weak_verneed_above_ceiling(self):
        with self.assertRaises(check_glibc.CheckError) as ctx:
            check_glibc.check_verneed(WEAK_FAIL_OUTPUT, '2.34')
        self.assertIn('GLIBC_2.39 (Flags: WEAK)', str(ctx.exception))

    def test_rejects_patch_version_above_ceiling(self):
        with self.assertRaises(check_glibc.CheckError) as ctx:
            check_glibc.check_verneed(PATCH_FAIL_OUTPUT, '2.34')
        self.assertIn('GLIBC_2.34.1', str(ctx.exception))

    def test_fails_closed_on_private_or_unparseable_output(self):
        for label, sample in (
            ('empty', ''),
            ('no_section', 'No version information found in this file.\n'),
            ('non_glibc_only', NON_GLIBC_ONLY_OUTPUT),
            ('private', PRIVATE_OUTPUT),
            ('unparseable_entry', UNPARSEABLE_ENTRY_OUTPUT),
        ):
            with self.subTest(label=label):
                with self.assertRaises(check_glibc.CheckError):
                    check_glibc.check_verneed(sample, '2.34')

    def test_fails_closed_on_missing_tool_or_missing_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'missing-bin'
            with self.assertRaises(check_glibc.CheckError):
                check_glibc.check_binary(missing)
            dummy = Path(tmp) / 'dummy-bin'
            dummy.write_bytes(b'not-an-elf')
            with self.assertRaises(check_glibc.CheckError) as ctx:
                check_glibc.check_binary(dummy, readelf='nonexistent-readelf-binary-xyz')
            self.assertIn('failed to execute', str(ctx.exception))

    def test_fails_closed_on_nonzero_readelf_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            dummy = Path(tmp) / 'dummy-bin'
            dummy.write_bytes(b'not-an-elf')
            fake = Path(tmp) / 'fake-readelf'
            fake.write_text('#!/bin/sh\necho "bad elf" >&2\nexit 2\n')
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            with self.assertRaises(check_glibc.CheckError) as ctx:
                check_glibc.check_binary(dummy, readelf=str(fake))
            self.assertIn('bad elf', str(ctx.exception))

    def test_cli_pass_and_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            dummy = Path(tmp) / 'openwiz'
            dummy.write_bytes(b'elf')
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(check_glibc, 'run_readelf', return_value=PASS_OUTPUT):
                with mock.patch.object(sys, 'stdout', out), mock.patch.object(sys, 'stderr', err):
                    rc = check_glibc.main(['--binary', str(dummy), '--max', '2.34'])
            self.assertEqual(rc, 0)
            self.assertIn('max GLIBC_2.34', out.getvalue())

            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(check_glibc, 'run_readelf', return_value=WEAK_FAIL_OUTPUT):
                with mock.patch.object(sys, 'stdout', out), mock.patch.object(sys, 'stderr', err):
                    rc = check_glibc.main(['--binary', str(dummy), '--max', '2.34'])
            self.assertEqual(rc, 1)
            self.assertIn('GLIBC_2.39 (Flags: WEAK)', err.getvalue())


if __name__ == '__main__':
    unittest.main()
