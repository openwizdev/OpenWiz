"""Private O15 binding of the reviewed O14 seam; no source-history import."""
import hashlib
import os
import shlex
import shutil
import tempfile
from pathlib import Path
import re
import subprocess
import sys

from plan import exact, parse_json, require

IMPORTER_SHA256 = '3b624db3ce0e38861245b106027eae4baa68002065e4fedeb79da62317267629'


def sha(value):
    return hashlib.sha256(value).hexdigest()


class Patch:
    def __init__(self, args, descriptor):
        exact(descriptor, ['source_base', 'source_head', 'destination', 'patch_dir', 'binding_sha256', 'observed_base'], 'PR handoff')
        require(all(type(v) is str for v in descriptor.values()) and
                all(re.fullmatch('[0-9a-f]{40}', descriptor[k]) for k in ['source_base', 'source_head', 'observed_base']) and
                re.fullmatch('[0-9a-f]{64}', descriptor['binding_sha256']), 'PR handoff: invalid identity')
        self.args, self.descriptor = args, descriptor
        require(sha(args.importer.read_bytes()) == IMPORTER_SHA256,
                'PR handoff: importer or carriage list differs from reviewed O14 delivery')
        raw = (Path(descriptor['patch_dir']) / 'binding.json').read_bytes()
        require(sha(raw) == descriptor['binding_sha256'], 'PR handoff: binding digest differs')
        self.binding = parse_json(raw.decode('utf-8'))
        require(type(self.binding) is dict, 'PR handoff: invalid binding')
        # The reviewed binding pins the carriage list it was prepared under.
        require(self.binding.get('policy_sha256') == sha((args.importer.parent / 'paths.json').read_bytes()),
                'PR handoff: importer or carriage list differs from reviewed O14 delivery')
        require(self.binding.get('source_base') == descriptor['source_base'] and
                self.binding.get('source_head') == descriptor['source_head'], 'PR handoff: source range differs')
        self.checked = self.run(False)

    def run(self, save):
        d, args = self.descriptor, self.args
        command = [sys.executable, '-I', str(args.importer), 'apply-patch', '--destination', d['destination'],
                   '--patch-dir', d['patch_dir'], '--binding-sha256', d['binding_sha256'],
                   '--checker', str(args.checker), '--literals', str(args.literals)]
        if save:
            command.append('--write-local')
        result = subprocess.run(command, capture_output=True, text=True)
        require(result.returncode == 0, 'PR handoff: O14 reapplication refused')
        value = parse_json(result.stdout)
        require(value.get('status') == 'checked' and value.get('tree') == self.binding['tree'] and
                value.get('destination_base') == self.binding['destination_base'] and
                type(value.get('commit')) is str and re.fullmatch('[0-9a-f]{40}', value['commit']) and
                'literals: used' in value.get('privacy', ''), 'PR handoff: incomplete O14 read-back')
        if save:
            require(value.get('saved') is True and value['commit'] == self.checked['commit'],
                    'PR handoff: saved commit differs')
        return value

    def git(self, root, *args, data=None):
        # The publication repository has no inherited config, refs or hooks.
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0',
                   GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1', GIT_GRAFT_FILE='/dev/null')
        result = subprocess.run([self.args.git, '-C', str(root), '-c', 'core.hooksPath=/dev/null', *args],
                                input=data, capture_output=True, env=env)
        require(result.returncode == 0, 'PR publish: Git outcome unconfirmed; inspect and resume')
        return result.stdout

    def publish(self, branch, target):
        value = self.run(True)
        # Only the checked commit's reachable public history enters scratch.
        # Source refs and destination tags/config never reach the publisher.
        packed = self.git(self.descriptor['destination'], 'pack-objects', '--stdout', '--revs',
                          data=(value['commit'] + '\n').encode())
        with tempfile.TemporaryDirectory(prefix='openwiz-publish-') as root:
            self.git(root, 'init', '--bare', '-q')
            gh = shutil.which(self.args.gh)
            require(gh is not None, 'PR publish: gh credential helper unavailable')
            helper = '!' + shlex.quote(str(Path(gh).resolve())) + ' auth git-credential'
            self.git(root, 'config', '--local', 'credential.https://github.com.helper', helper)
            self.git(root, 'unpack-objects', '-q', data=packed)
            self.git(root, 'push', '--no-verify', '--no-follow-tags', '--recurse-submodules=no',
                     'https://github.com/' + target + '.git', value['commit'] + ':refs/heads/' + branch)
