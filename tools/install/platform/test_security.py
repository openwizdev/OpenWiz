import importlib.util
import ast
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('key_boundary', Path(__file__).with_name('security.py'))
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)

class Security(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='openwiz-key-boundary-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = self.root/'service/app'
        self.app.mkdir(parents=True, mode=0o700)
        self.app.parent.chmod(0o700)
        self.key = self.app/'private-key.pem'
        self.key.write_bytes(b'synthetic-pinned-key')
        self.key.chmod(0o600)

    def test_owner_mode_symlink_hardlink_fifo_and_repository_refusals(self):
        fd = security.open_key(str(self.root))
        self.assertEqual(os.read(fd,100), b'synthetic-pinned-key')
        os.close(fd)
        for path in (self.root,self.app.parent,self.app,self.key):
            mode = stat.S_IMODE(path.stat().st_mode)
            path.chmod(mode | 0o020)
            with self.assertRaises(ValueError): security.open_key(str(self.root))
            path.chmod(mode)
        with patch.object(security.os, 'geteuid', return_value=os.geteuid()+1):
            with self.assertRaises(ValueError): security.open_key(str(self.root))
        alias = self.app/'alias'
        os.link(self.key,alias)
        with self.assertRaises(ValueError): security.open_key(str(self.root))
        alias.unlink()
        saved = self.app/'original'
        self.key.rename(saved)
        self.key.symlink_to(saved)
        with self.assertRaises(OSError): security.open_key(str(self.root))
        self.key.unlink()
        os.mkfifo(self.key,0o600)
        with self.assertRaises(ValueError): security.open_key(str(self.root))
        self.key.unlink()
        saved.rename(self.key)
        (self.root/'.git').write_bytes(b'synthetic repository marker')
        with self.assertRaises(ValueError): security.open_key(str(self.root))

    def test_symlinked_state_service_and_app_directories_are_refused(self):
        for path in (self.root,self.app.parent,self.app):
            with self.subTest(component=path.relative_to(self.root).as_posix()):
                target = path.with_name(path.name+'-private-target')
                path.rename(target)
                path.symlink_to(target,target_is_directory=True)
                try:
                    with self.assertRaises((OSError,ValueError)):
                        fd = security.open_key(str(self.root))
                        os.close(fd)
                finally:
                    path.unlink()
                    target.rename(path)

    def test_fixed_signing_boundary_reads_executable_calls_not_comments(self):
        source = Path(__file__).with_name('security.py').read_text()
        def allowed(code):
            tree = ast.parse(code)
            calls = [node for node in ast.walk(tree) if isinstance(node,ast.Call)
                     and isinstance(node.func,ast.Attribute)
                     and isinstance(node.func.value,ast.Name) and node.func.value.id == 'os']
            execs = [node for node in calls if node.func.attr == 'execve']
            inherit = [node for node in calls if node.func.attr == 'set_inheritable']
            expected = ast.parse("os.execve('/usr/bin/openssl',['/usr/bin/openssl','dgst','-sha256','-sign','/dev/fd/'+str(key)],{})").body[0].value
            pinned = ast.parse('os.set_inheritable(key,True)').body[0].value
            return (len(execs) == len(inherit) == 1 and ast.dump(execs[0]) == ast.dump(expected)
                    and ast.dump(inherit[0]) == ast.dump(pinned))
        self.assertTrue(allowed(source))
        for changed in (
            source.replace("'/dev/fd/'+str(key)","sys.argv[2]"),
            source.replace('os.set_inheritable(key, True)','pass # os.set_inheritable(key, True)'),
            source.replace("'/usr/bin/openssl'","'/bin/sh'"),
            source.replace('], {})','], os.environ)'),
        ):
            self.assertFalse(allowed(changed))

    def test_nested_repository_markers_are_refused(self):
        for directory in (self.app.parent,self.app):
            marker = directory/'.git'
            marker.write_bytes(b'gitdir: synthetic-only')
            with self.assertRaises(ValueError): security.open_key(str(self.root))
            marker.unlink()

    def test_rename_after_open_cannot_substitute_the_key(self):
        fd = security.open_key(str(self.root))
        self.key.rename(self.app/'old')
        self.key.write_bytes(b'synthetic-replacement')
        self.assertEqual(os.read(fd,100), b'synthetic-pinned-key')
        os.close(fd)

    def test_real_signing_inherits_only_the_pinned_key_and_exposes_no_material(self):
        result = subprocess.run(['/usr/bin/openssl','genpkey','-algorithm','RSA',
             '-pkeyopt','rsa_keygen_bits:2048','-out',str(self.key)], capture_output=True)
        self.assertEqual(result.returncode,0)
        self.key.chmod(0o600)
        key_bytes = self.key.read_bytes()
        real_run = subprocess.run
        calls = []
        def record(program, args, env):
            calls.append((args,env))
            self.assertEqual(program,"/usr/bin/openssl")
            self.assertEqual(args[:4], ['/usr/bin/openssl','dgst','-sha256','-sign'])
            fd = int(args[-1].removeprefix('/dev/fd/'))
            self.assertTrue(os.get_inheritable(fd))
            self.assertEqual(env,{})
            self.assertNotIn(key_bytes.decode(),str(args))
            self.key.rename(self.app/'saved')
            self.key.write_bytes(b'synthetic invalid replacement')
            result = real_run(args, input=b'synthetic.message', pass_fds=(fd,), env=env, capture_output=True)
            self.assertEqual(result.returncode,0)
            sys.stdout.buffer.write(result.stdout)
        class Input:
            buffer = __import__('io').BytesIO(b'synthetic.message')
        class Output:
            buffer = __import__('io').BytesIO()
        output = Output()
        with patch.object(sys,'argv',['security','sign',str(self.root)]), \
             patch.object(sys,'stdin',Input()), patch.object(sys,'stdout',output), \
             patch.object(security.os,'execve',record):
            security.main()
        self.assertEqual(len(calls),1)
        signature = self.root/'signature'
        signature.write_bytes(output.buffer.getvalue())
        public = self.root/'public'
        extracted = real_run(['/usr/bin/openssl','pkey','-in',str(self.app/'saved'),'-pubout'],capture_output=True)
        self.assertEqual(extracted.returncode,0)
        public.write_bytes(extracted.stdout)
        verified = real_run(['/usr/bin/openssl','dgst','-sha256','-verify',str(public),
                    '-signature',str(signature)],input=b'synthetic.message',capture_output=True)
        self.assertEqual(verified.returncode,0)

if __name__ == '__main__':
    unittest.main()
