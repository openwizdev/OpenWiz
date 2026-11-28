#!/usr/bin/env python3
import re
import sys
from pathlib import Path

FILES = ('README.md', 'docs/install.md')
REQUIRED = re.compile(r'(?i)\bneeds? \[?CloudRoom\b|\brequires? \[?CloudRoom\b|\bCloudRoom\]?(?:\([^)]*\))?(?:,? is)? required'
                      r'|\bYou need \[?CloudRoom|done only when CloudRoom|sets up through (?:it|CloudRoom)')
HOSTS = ('this computer', 'boat.dev', 'CloudRoom')


def paragraphs(text):
    return [p for p in re.split(r'\n\s*\n', text) if p.strip()]


def sentences(paragraph):
    return re.split(r'(?<=[.!?;])\s+', ' '.join(paragraph.split()))


def check(name, text):
    failures = []
    for number, line in enumerate(text.splitlines(), 1):
        if REQUIRED.search(line):
            failures.append(f'{name}:{number}: says CloudRoom is required: {REQUIRED.search(line).group(0)!r}')
        if 'cloudroom.py install' in line and 'only if you pick' not in line:
            failures.append(f'{name}:{number}: runs CloudRoom\'s install without "only if you pick" it')

    before = re.search(r'^## Before you start\n(.*?)^## ', text, re.M | re.S)
    for bullet in re.findall(r'^- .*$', before.group(1), re.M) if before else ():
        if re.match(r'- \*\*[^*]*CloudRoom', bullet) and 'optional' not in bullet:
            failures.append(f'{name}: "Before you start" lists CloudRoom without saying it is optional: {bullet[:60]!r}')

    def hosts_in_order(line):
        flat = ' '.join(line.split())
        at = [flat.find(host) for host in HOSTS]
        return -1 not in at and at == sorted(at) and 'CloudRoom is optional' in flat

    if not any(hosts_in_order(line) for line in text.splitlines()):
        failures.append(f'{name}: no line names this computer, boat.dev and CloudRoom in that order and says '
                        '"CloudRoom is optional"')
    said_010 = said_011 = False
    for paragraph in paragraphs(text):
        for sentence in sentences(paragraph):
            if 'automatic fleet' not in sentence:
                continue
            if '0.1.0' in sentence and 'CloudRoom' in sentence:
                said_010 = True
            if '0.1.1' in sentence and 'this computer' in sentence:
                said_011 = True
    if not said_010:
        failures.append(f'{name}: never says that on 0.1.0 the automatic fleet runs in CloudRoom')
    if not said_011:
        failures.append(f'{name}: never says that 0.1.1 runs the automatic fleet on this computer')
    failures += release_path(name, text)
    return failures


def section_010(text):
    match = re.search(r'^#+ [^\n]*0\.1\.0[^\n]*\n(.*?)(?=^#+ |\Z)', text, re.M | re.S)
    return match.group(0) if match else ''


def release_path(name, text):
    failures = []
    old = section_010(text)
    default = text.replace(old, '') if old else text
    if not old:
        failures.append(f'{name}: no clearly marked 0.1.0 section (a heading naming 0.1.0)')
    if 'blob/maint/0.2/' in default:
        failures.append(f'{name}: the default path links the 0.1.0 maintenance skill (maint/0.2)')
    if name in ('README.md', 'docs/install.md'):
        if 'WizSkills/blob/v0.4.0/' in text or 'WizSkills 0.4.0' in text:
            failures.append(f'{name}: pins WizSkills 0.4.0')
        if '--branch v0.1.1' in text:
            failures.append(f'{name}: clones the fixed v0.1.1 tag')
        if 'wizskills.lock' not in default:
            failures.append(f'{name}: the default path does not derive the skill from wizskills.lock')
        if 'git clone --depth 1 --branch "$tag" -- https://github.com/openwizdev/OpenWiz' not in default:
            failures.append(f'{name}: the default path does not clone the release tag with -- before the repository')
        if 'v(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)' not in default:
            failures.append(f'{name}: the default path does not check the whole tag against a strict pattern')
    if re.search(r'Intel Mac[^.]*from 0\.1\.1', text):
        failures.append(f'{name}: says an Intel Mac installs only from 0.1.1')
    if re.search(r'(?i)wakes the fleet every ten minutes', text):
        failures.append(f'{name}: says the schedule wakes the fleet every ten minutes')
    if name == 'README.md' and 'docs/install.md#openwiz-010' not in old:
        failures.append(f'{name}: the 0.1.0 section does not point to the guide\'s explicit 0.1.0 steps')
    if name == 'docs/install.md':
        if "'^version: 0.2.2$'" in default or '--branch maint/0.2' in default:
            failures.append(f'{name}: the default path still overwrites the install skill with maint/0.2')
        if 'prints the version (`0.1.1`)' not in default:
            failures.append(f'{name}: the build identity check does not expect 0.1.1')
        flat = ' '.join(text.split())
        if not re.search(r'every ten minutes[^.]*only when', flat):
            failures.append(f'{name}: never says the heartbeat checks every ten minutes and wakes only when work is due')
        if not re.search(r'heartbeat[^.]*boat\.dev|boat\.dev[^.]*heartbeat', flat):
            failures.append(f'{name}: never says boat.dev fleets use the local heartbeat too')
        if '`jq`' not in flat:
            failures.append(f'{name}: never lists jq as a heartbeat prerequisite')
        if 'same-family review' not in flat:
            failures.append(f'{name}: never says a review by the same family is marked')
        remove = re.search(r'^## Remove it\n(.*?)(?=^## |\Z)', text, re.M | re.S)
        body = remove.group(1) if remove else ''
        for needed in ('heartbeat.py remove', 'heartbeat.py pause', 'install remove'):
            if needed not in body:
                failures.append(f'{name}: "Remove it" never names `{needed}`')
        if 'There is no remove command' in default:
            failures.append(f'{name}: says there is no remove command')
        if not re.search(r"boat\.dev[^.]*dashboard[^.]*write access[^.]*(?:harness|Claude Code or Codex)[^.]*key", flat):
            failures.append(f'{name}: the boat.dev prerequisites omit GitHub write access and the harness key in boat\'s dashboard')
        if 'releases/download/v0.1.0/' not in old or 'install install --assets' not in old:
            failures.append(f'{name}: the 0.1.0 section does not select the v0.1.0 files explicitly')
        if "which runs the fleet's orchestrator" in flat:
            failures.append(f'{name}: says this computer runs the orchestrator for boat.dev too')
        if not re.search(r'orchestrator[^.]*boat\.dev sandbox', flat):
            failures.append(f'{name}: never says the orchestrator starts in a boat.dev sandbox when boat.dev is the host')
        if not re.search(r'"run the fleet now"[^.]*(?:paused|active)', flat):
            failures.append(f'{name}: "run the fleet now" is not qualified for a paused job')
        if 'Delete only those named folders' in body:
            failures.append(f'{name}: tells the reader to delete the listed skill folders, which are shared parents')
        if 'never the listed folder itself' not in body:
            failures.append(f'{name}: never says to keep each listed skills folder itself')
    return failures


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.')
    failures = []
    for name in FILES:
        failures += check(name, (root / name).read_text(encoding='utf-8'))
    for failure in failures:
        print('FAIL', failure)
    print('ok: README.md and docs/install.md say CloudRoom is optional' if not failures
          else f'{len(failures)} failures')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
