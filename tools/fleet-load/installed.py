"""Run the installed tick's real dispatcher over FA3's initial frontier.

Reuses the existing B5 recording executor, without copying or modifying it.
Only the fixture CLI example can be selected; production binaries are refused.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def run(world):
    # Cargo's target configuration can move the executable below a target
    # triple. Select the artifact emitted by this build, never a guessed path.
    build = subprocess.run(['cargo', 'build', '--locked', '-p', 'openwiz-tests', '--example', 'openwiz', '-j', '2',
                            '--target-dir', str(ROOT / 'target'), '--message-format=json'],
                           cwd=ROOT, check=True, timeout=300, text=True, capture_output=True)
    artifacts = []
    for line in build.stdout.splitlines():
        event = json.loads(line)
        assert type(event) is dict, 'malformed Cargo build message'
        target = event.get('target', {})
        if event.get('reason') == 'compiler-artifact' and target.get('name') == 'openwiz' and target.get('kind') == ['example']:
            binary = Path(event['executable'])
            assert binary.is_absolute() and binary.resolve().is_relative_to((ROOT / 'target').resolve()), 'Cargo example outside selected output'
            assert Path(event['manifest_path']).resolve().is_relative_to(ROOT.resolve()), 'Cargo example outside candidate checkout'
            assert binary.is_file(), 'Cargo example is missing'
            artifacts.append(binary)
    assert len(artifacts) == 1, 'Cargo did not identify exactly one installed-tick example'
    binary = artifacts[0]
    source = (ROOT / 'tests/fleet/b5_fake.rs').read_text()
    script = source.split('const SCRIPT: &str = r#"', 1)[1].rsplit('"#;', 1)[0]
    node = shutil.which('node')
    assert node, 'installed tick fixture requires the project Node installation'
    issues, comments = [], {}
    def ms(value):
        import datetime
        return int(datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)
    for i in world['issues']:
        issues.append(dict(n=i['number'], title=i['title'], body=i['body'],
                           subs=[x['number'] for x in world['issues'] if x.get('parent') == i['number']],
                           blockers=i['blockedBy'], labels=i['labels'], closed=False))
        comments[str(i['number'])] = [dict(id=c['id'], body=c['body'], created=ms(c['at']), updated=ms(c['at'])) for c in i['comments']]
    for i in issues:
        if not i['subs']:
            continue
        revision = f"plan-graph revision v2\nspec #{i['n']} body sha256 {hashlib.sha256((i['body'] + chr(10)).encode()).hexdigest()}\n"
        for child in sorted((x for x in issues if x['n'] in i['subs']), key=lambda x: x['n']):
            blockers = ' '.join('#' + str(n) for n in sorted(child['blockers'])) or 'none'
            revision += f"ticket #{child['n']} blocked-by {blockers} body sha256 {hashlib.sha256((child['body'] + chr(10)).encode()).hexdigest()} title {child['title']}\n"
        approval = comments[str(i['n'])][0]
        assert hashlib.sha256(revision.encode()).hexdigest() in approval['body'], 'FA3 revision translation mismatch'
        approval['body'] += '\n\n```text\n' + revision + '```\n'
    state = dict(issues=issues, prs=[], comments=comments, threads={}, base='b' * 40,
                 rules=(ROOT / 'docs/agents/fleet.md').read_text(), next=10000, spawn_count=0,
                 overrides={}, crash='', timeline={}, fail_record='', merge_bodies=[])
    with tempfile.TemporaryDirectory(prefix='fa3-installed-') as name:
        root = Path(name)
        fake = root / 'fake.cjs'
        fake.write_text(script.replace('#!/usr/bin/env node', '#!' + node, 1)); fake.chmod(0o700)
        for tool in ('gh', 'room-cli'):
            (root / tool).symlink_to(fake)
        (root / 'world.json').write_text(json.dumps(state))
        env = {k: v for k, v in os.environ.items() if not k.startswith(('OPENWIZ_', 'GH_', 'GITHUB_', 'FAKE_', 'LOAD_', 'LAUNCH_FLEET_'))}
        env.update(PATH=str(root) + ':' + env['PATH'], OPENWIZ_FIXTURE_PROGRAM=str(root / 'room-cli'),
                   OPENWIZ_STATE_DIR=str(root / 'state'))
        before = time.monotonic()
        completed = subprocess.run([str(binary), 'fleet', 'tick', '--dry-run', '--json'], cwd=root,
                                   env=env, capture_output=True, text=True, timeout=120)
        assert completed.returncode == 0, completed.stderr
        doc = json.loads(completed.stdout)
        assert doc['schema'] == 'openwiz.fleet-tick.v1' and doc['mode'] == 'dry_run'
        expected = {i['n'] for i in issues if i['labels'] == ['ready-for-agent'] and not i['blockers']}
        actual = {a['ticket'] for a in doc['actions'] if a['kind'] == 'start_builder' and a['rule'] == 'frontier'}
        assert actual == expected and len(expected) == 95, f'installed frontier mismatch: {doc["actions"][:3]}; got {len(actual)}'
        assert all(a['outcome']['state'] == 'planned' for a in doc['actions'])
        calls = [json.loads(line) for line in (root / 'calls.log').read_text().splitlines()]
        assert not any(a[0] == 'thread' and a[1] in ('spawn', 'tell', 'archive') for _, a in calls), 'installed dry-run wrote CloudRoom'
        assert not any(tool == 'gh' and len(a) > 1 and a[1] in ('comment', 'edit', 'merge', 'close') for tool, a in calls), 'installed dry-run wrote GitHub'
        assert not (root / 'state').exists(), 'installed dry-run wrote state'
        return dict(tickets=100, frontier=len(actual), mode=doc['mode'], commands=len(calls),
                    wall_ms=round((time.monotonic() - before) * 1000, 3),
                    binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                    fixture_sha256=hashlib.sha256(source.encode()).hexdigest())
