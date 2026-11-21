#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check

DESCRIPTION = """Pre-push adapter: guard network destinations except the private repository."""


def private_or_local(url):
    if url.startswith(('/', './', '../', 'file://')):
        return True
    if '://' in url:
        value = urlsplit(url)
        host, path = value.hostname, value.path
    else:
        match = re.fullmatch(r'(?:[^/@:]+@)?([^/:]+):(.+)', url)
        if not match:
            return bool(url) and ':' not in url
        host, path = match.groups()
    path = path.strip('/').removesuffix('.git').lower()
    return host and host.lower() == 'github.com' and path == 'jparker2006/closedwiz'


PUBLIC_URLS = (
    'https://github.com/openwizdev/OpenWiz',
    'https://github.com/openwizdev/OpenWiz.git',
    'git@github.com:openwizdev/OpenWiz',
    'git@github.com:openwizdev/OpenWiz.git',
    'https://github.com/openwizdev/openwiz',
    'https://github.com/openwizdev/openwiz.git',
    'git@github.com:openwizdev/openwiz',
    'git@github.com:openwizdev/openwiz.git',
)
HOOK_GIT_VARIABLES = ('GIT_EXEC_PATH', 'GIT_PREFIX', 'GIT_EDITOR')


def narrowable(url, env):
    if url not in PUBLIC_URLS:
        return False
    extra = {k for k in env if k.startswith('GIT_') and k not in HOOK_GIT_VARIABLES}
    if not extra:
        return True
    count = env.get('GIT_CONFIG_COUNT', '')
    if not re.fullmatch(r'0|[1-9][0-9]{0,3}', count):
        return False
    keys = ['GIT_CONFIG_KEY_%d' % i for i in range(int(count))]
    values = ['GIT_CONFIG_VALUE_%d' % i for i in range(int(count))]
    if extra != {'GIT_CONFIG_COUNT', *keys, *values}:
        return False
    return all(env[k].startswith('hook.') for k in keys)


def destination_main(repo, url):
    if not narrowable(url, os.environ):
        return None
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1'}
    def run(*args, timeout=60):
        result = subprocess.run(['git', '-C', str(repo), *args], env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=timeout)
        return result.stdout if result.returncode == 0 else None
    try:
        keys = run('config', '--null', '--name-only', '--list')
        if keys is None or any(k.partition('.')[0].lower() == 'remote' and k.partition('.')[2].rpartition('.')[0] == url
                               for k in keys.split('\0')):
            return None
        if run('ls-remote', '--get-url', url) != url + '\n':
            return None
        listed = run('ls-remote', '--refs', url, 'refs/heads/main')
        mains = [line.split('\t')[0] for line in (listed or '').splitlines() if line.endswith('\trefs/heads/main')]
        if len(mains) != 1 or not re.fullmatch(r'[0-9a-f]{40}', mains[0]):
            return None
        if run('cat-file', '-e', mains[0] + '^{commit}') is None and run(
                '-c', 'fetch.bundleURI=', '-c', 'transfer.bundleURI=false', '-c', 'promisor.acceptFromServer=None',
                'fetch', '--quiet', '--no-tags', '--no-recurse-submodules', '--no-write-fetch-head',
                '--no-auto-maintenance', '--no-filter', url, 'refs/heads/main', timeout=300) is None:
            return None
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    return mains[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--url', required=True)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--head', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--literals', type=Path, default=os.environ.get('OPENWIZ_PRIVACY_LITERALS'))
    args = parser.parse_args(argv)
    if private_or_local(args.url):
        return 0
    command = ['--repo', str(args.repo), '--git-tree', args.head, '--head', args.head]
    if args.base.strip('0'):
        command += ['--base', args.base]
    else:
        main = destination_main(args.repo, args.url)
        if main:
            command += ['--upstream', main]
    if args.literals is not None:
        command += ['--literals', str(args.literals), '--require-literals']
    return check.main(command)


if __name__ == '__main__':
    sys.exit(main())
