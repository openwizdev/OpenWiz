#!/usr/bin/env python3
"""WZ7 (#2632) proofs for WizSkills' own check, on synthetic trees only.

python3 -I tools/skills-copy/package-check/test_check.py

Each test builds a WizSkills-shaped tree in a temporary directory, places
check/run.py there exactly as the copy does, and runs it as the workflow
does: `python3 check/run.py` from the tree's root. Nothing from ClosedWiz is
present in the tree, so a pass also shows the check needs no ClosedWiz path.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # the proofs leave no file in the source tree

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2]
RUN = HERE / 'check' / 'run.py'
WORKFLOW = HERE / 'ci.yml'

# Matt Pocock's MIT notice, from `LICENSE` in github.com/mattpocock/skills
# @ a496f55, as skills/README.md and tests/checks/skills.rs pin it.
MATT = """Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

# The source lines skills/README.md lists for the two skills it names.
IMAGE_SOURCE = "**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills."
WHERE_SOURCE = "**Source:** dot-context's written plan. Not adapted from Matt Pocock's skills."
# WZ6's feedback and WZ13's install (#2891) carry the original-source line too.
SOURCE_LINES = {'feedback': IMAGE_SOURCE, 'hill-climb': IMAGE_SOURCE, 'image': IMAGE_SOURCE,
                'install': IMAGE_SOURCE, 'where-are-we': WHERE_SOURCE}

# The suites ci/select/skills.py runs today, by skill and command; the
# suites runner must run every one of these from the tree's root.
SUITE_SKILLS = ['triage', 'where-are-we', 'hill-climb', 'image', 'plan-graph', 'launch-fleet']
SKILLS = sorted(SUITE_SKILLS + ['ask-wiz', 'feedback', 'install'])

# The one command ci/select/skills.py runs that is a ClosedWiz tool, not a
# skill's own file: WizSkills cannot carry it (contracts/wizskills.v1.md).
CLOSEDWIZ_ONLY = ['python3', '-I', 'tools/review-relay/test_inbox.py']

RECORDER = 'import pathlib, sys\nwith open("ran.txt", "a") as f:\n    f.write({!r} + "\\n")\n'


def load_run():
    spec = importlib.util.spec_from_file_location('wizskills_check_run', RUN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, text, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode:
        path.chmod(mode)


def skill_md(name, extra_front='', body=None):
    front = f'---\nname: {name}\ndescription: Synthetic skill {name} for the check.\n{extra_front}---\n'
    if body is None:
        if name in SOURCE_LINES:
            body = f'\n# {name}\n\n{SOURCE_LINES[name]}\n\nSee [the rules](../README.md#rules).\n'
        else:
            body = f'\n# {name}\n\nSee [the rules](../README.md).\n\n## Licence\n\n{MATT}'
    return front + body


def openai_yaml(name):
    text = f'interface:\n  display_name: "{name.title()}"\n  short_description: "Synthetic {name}"\n'
    if name == 'ask-wiz':
        text += 'policy:\n  allow_implicit_invocation: false\n'
    return text


def suite_files(root):
    """Fake suite scripts at the listed paths; each records its own run."""
    marker = {
        'triage': [('skills/triage/test/test_find_work.py', 'py')],
        'where-are-we': [('skills/where-are-we/test/test_read_github.py', 'py')],
        'hill-climb': [('skills/hill-climb/tests/test_synthetic.py', 'unit')],
        'image': [('skills/image/tests/test_synthetic.py', 'unit')],
        'plan-graph': [('skills/plan-graph/scripts/test_check_approval.py', 'py'),
                       ('skills/plan-graph/test/test-revision.sh', 'sh')],
        'launch-fleet': [('skills/launch-fleet/scripts/test.sh', 'sh'),
                         ('skills/launch-fleet/test/ops-protocol/test_protocol.py', 'py'),
                         ('skills/launch-fleet/scripts/test-effects.py', 'py'),
                         ('skills/launch-fleet/scripts/test-grants.py', 'py'),
                         ('skills/launch-fleet/scripts/test-inbox.py', 'py')],
    }
    for files in marker.values():
        for rel, kind in files:
            if kind == 'sh':
                write(root / rel, f'#!/bin/sh\necho {rel} >> ran.txt\n')
            elif kind == 'py':
                write(root / rel, RECORDER.format(rel))
            else:
                write(root / rel, RECORDER.format(rel) + 'import unittest\n\n\n'
                      'class T(unittest.TestCase):\n    def test_ok(self):\n        pass\n')
    return sorted(rel for files in marker.values() for rel, _ in files)


# A stand-in scanner that passes only for the scanner's real interface,
# `--tree <root>` (WZ2), so a call without `--tree` fails as the real one does.
STANDALONE = ('import pathlib, sys\n'
              'ok = len(sys.argv) == 3 and sys.argv[1] == "--tree" and '
              'pathlib.Path(sys.argv[2]).resolve() == pathlib.Path(__file__).resolve().parent.parent\n'
              'sys.exit(0 if ok else 2)\n')


def build(root):
    """A valid synthetic WizSkills tree, and the suite files it holds."""
    write(root / 'skills/README.md', '# Skills\n\n## Rules\n\nSynthetic rules.\n')
    for name in SKILLS:
        extra = 'disable-model-invocation: true\n' if name == 'ask-wiz' else ''
        write(root / f'skills/{name}/SKILL.md', skill_md(name, extra))
        write(root / f'skills/{name}/agents/openai.yaml', openai_yaml(name))
    plugin = {'name': 'openwiz', 'version': '0.1.0', 'description': 'Synthetic skills.',
              'author': {'name': 'Synthetic'}, 'skills': [f'./skills/{n}' for n in SKILLS]}
    market = {'name': 'wizskills', 'owner': {'name': 'Synthetic'},
              'plugins': [{'name': 'openwiz', 'source': './', 'description': 'Synthetic.'}]}
    write(root / '.claude-plugin/plugin.json', json.dumps(plugin, indent=2))
    write(root / '.claude-plugin/marketplace.json', json.dumps(market, indent=2))
    (root / 'check').mkdir()
    shutil.copy2(RUN, root / 'check/run.py')
    write(root / 'check/standalone.py', STANDALONE)
    return suite_files(root)


def run(root):
    env = {k: v for k, v in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN')}
    done = subprocess.run([sys.executable, 'check/run.py'], cwd=root, env=env,
                          capture_output=True, text=True, timeout=120)
    return done.returncode, done.stdout + done.stderr


def ran(root):
    path = root / 'ran.txt'
    return sorted(path.read_text().split()) if path.exists() else []


class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / 'wizskills'
        self.root.mkdir()
        self.suites = build(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def json(self, rel, change):
        path = self.root / rel
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def refused(self, rule, file):
        code, out = run(self.root)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, rf'(?m)^rules: {re.escape(rule)} {re.escape(file)}(:\d+)?: ', out)
        return out


class ValidTree(Tree):
    def test_valid_tree_passes_and_runs_every_suite(self):
        code, out = run(self.root)
        self.assertEqual(code, 0, out)
        self.assertEqual(ran(self.root), self.suites)
        self.assertIn('rules: pass', out)
        self.assertIn('standalone: pass', out)


class Frontmatter(Tree):
    def test_an_extra_key_is_refused(self):
        write(self.root / 'skills/triage/SKILL.md', skill_md('triage', 'license: MIT\n'))
        self.refused('frontmatter', 'skills/triage/SKILL.md')

    def test_name_must_be_the_folder(self):
        text = skill_md('triage').replace('name: triage', 'name: sorting', 1)
        write(self.root / 'skills/triage/SKILL.md', text)
        self.refused('frontmatter', 'skills/triage/SKILL.md')

    def test_only_ask_wiz_may_disable_model_invocation(self):
        write(self.root / 'skills/triage/SKILL.md',
              skill_md('triage', 'disable-model-invocation: true\n'))
        self.refused('frontmatter', 'skills/triage/SKILL.md')

    def test_ask_wiz_requires_disable_model_invocation(self):
        write(self.root / 'skills/ask-wiz/SKILL.md', skill_md('ask-wiz'))
        self.refused('frontmatter', 'skills/ask-wiz/SKILL.md')

    def test_a_value_yaml_misreads_is_refused(self):
        text = skill_md('triage').replace('description: Synthetic', 'description: Sort: synthetic', 1)
        write(self.root / 'skills/triage/SKILL.md', text)
        self.refused('frontmatter', 'skills/triage/SKILL.md')

    def test_missing_frontmatter_is_refused(self):
        write(self.root / 'skills/triage/SKILL.md', '# triage\n\n' + MATT)
        self.refused('frontmatter', 'skills/triage/SKILL.md')


class Codex(Tree):
    def test_a_missing_openai_yaml_is_refused(self):
        (self.root / 'skills/triage/agents/openai.yaml').unlink()
        self.refused('codex', 'skills/triage/agents/openai.yaml')

    def test_policy_is_refused_outside_ask_wiz(self):
        path = self.root / 'skills/triage/agents/openai.yaml'
        path.write_text(path.read_text() + 'policy:\n  allow_implicit_invocation: false\n')
        self.refused('codex', 'skills/triage/agents/openai.yaml')

    def test_ask_wiz_requires_its_policy(self):
        write(self.root / 'skills/ask-wiz/agents/openai.yaml', openai_yaml('triage'))
        self.refused('codex', 'skills/ask-wiz/agents/openai.yaml')

    def test_an_unknown_interface_field_is_refused(self):
        path = self.root / 'skills/triage/agents/openai.yaml'
        path.write_text(path.read_text() + '  brand_color: "#000000"\n')
        self.refused('codex', 'skills/triage/agents/openai.yaml')

    def test_a_missing_interface_field_is_refused(self):
        write(self.root / 'skills/triage/agents/openai.yaml', 'interface:\n  display_name: "Triage"\n')
        self.refused('codex', 'skills/triage/agents/openai.yaml')


class Notice(Tree):
    def test_matts_notice_must_be_word_for_word(self):
        text = skill_md('triage').replace('free of charge', 'for free', 1)
        write(self.root / 'skills/triage/SKILL.md', text)
        self.refused('notice', 'skills/triage/SKILL.md')

    def test_line_breaks_in_the_notice_do_not_matter(self):
        text = skill_md('triage').replace('obtaining a copy\nof this', 'obtaining a\ncopy of this', 1)
        write(self.root / 'skills/triage/SKILL.md', text)
        code, out = run(self.root)
        self.assertEqual(code, 0, out)

    def test_a_listed_skill_carries_its_source_line(self):
        text = skill_md('image').replace(IMAGE_SOURCE, '**Source:** original.', 1)
        write(self.root / 'skills/image/SKILL.md', text)
        self.refused('notice', 'skills/image/SKILL.md')

    def test_a_listed_skill_never_carries_matts_notice(self):
        write(self.root / 'skills/image/SKILL.md', skill_md('image') + '\n' + MATT)
        self.refused('notice', 'skills/image/SKILL.md')

    def test_where_are_we_has_its_own_source_line(self):
        text = skill_md('where-are-we').replace(WHERE_SOURCE, IMAGE_SOURCE, 1)
        write(self.root / 'skills/where-are-we/SKILL.md', text)
        self.refused('notice', 'skills/where-are-we/SKILL.md')


    def test_feedback_and_install_carry_the_original_source_line(self):
        for name in ('feedback', 'install'):
            with self.subTest(name=name):
                build_text = skill_md(name)
                self.assertIn(IMAGE_SOURCE, build_text)
                write(self.root / f'skills/{name}/SKILL.md',
                      build_text.replace(IMAGE_SOURCE, IMAGE_SOURCE.replace('new, ', ''), 1))
                self.refused('notice', f'skills/{name}/SKILL.md')
                write(self.root / f'skills/{name}/SKILL.md', build_text.replace(IMAGE_SOURCE, WHERE_SOURCE, 1))
                self.refused('notice', f'skills/{name}/SKILL.md')
                write(self.root / f'skills/{name}/SKILL.md', build_text.replace(IMAGE_SOURCE, '', 1))
                self.refused('notice', f'skills/{name}/SKILL.md')
                write(self.root / f'skills/{name}/SKILL.md', build_text + '\n' + MATT)
                self.refused('notice', f'skills/{name}/SKILL.md')
                write(self.root / f'skills/{name}/SKILL.md', build_text)

    def test_the_source_line_must_be_on_a_line_of_its_own(self):
        text = skill_md('install').replace(IMAGE_SOURCE, 'See: ' + IMAGE_SOURCE, 1)
        write(self.root / 'skills/install/SKILL.md', text)
        self.refused('notice', 'skills/install/SKILL.md')

    def test_an_unlisted_skill_still_needs_matts_notice(self):
        write(self.root / 'skills/triage/SKILL.md', skill_md('triage', body=f'\n# triage\n\n{IMAGE_SOURCE}\n'))
        self.refused('notice', 'skills/triage/SKILL.md')


class Links(Tree):
    def test_a_relative_link_that_does_not_resolve_is_refused(self):
        path = self.root / 'skills/triage/SKILL.md'
        path.write_text(path.read_text() + '\nSee [missing](scripts/missing.md).\n')
        out = self.refused('links', 'skills/triage/SKILL.md')
        self.assertNotIn('scripts/missing.md', out)

    def test_a_link_leaving_the_tree_is_refused(self):
        write(self.tmp / 'outside.md', 'synthetic outside file\n')
        path = self.root / 'skills/triage/notes.md'
        write(path, 'Line one.\nSee [out](../../../outside.md).\n')
        out = self.refused('links', 'skills/triage/notes.md')
        self.assertIn('skills/triage/notes.md:2:', out)

    def test_a_reference_link_is_checked(self):
        write(self.root / 'skills/triage/notes.md', '[gone]: ../nowhere/README.md\n')
        self.refused('links', 'skills/triage/notes.md')

    def test_encoded_and_anchor_links_resolve(self):
        write(self.root / 'skills/triage/two words.md', '# Two\n')
        write(self.root / 'skills/triage/notes.md',
              '[a](two%20words.md#two) [b](#local) [c](https://example.invalid/x.md)\n'
              '`[d](missing.md)`\n\n```\n[e](missing.md)\n```\n')
        code, out = run(self.root)
        self.assertEqual(code, 0, out)

    def test_a_symlink_inside_skills_is_refused(self):
        os.symlink('../README.md', self.root / 'skills/triage/README.md')
        self.refused('symlink', 'skills/triage/README.md')

    def test_a_symlinked_skill_folder_is_refused(self):
        os.symlink('triage', self.root / 'skills/sorting')
        self.refused('symlink', 'skills/sorting')


class Manifest(Tree):
    PLUGIN = '.claude-plugin/plugin.json'
    MARKET = '.claude-plugin/marketplace.json'

    def test_a_carried_skill_missing_from_the_manifest_is_refused(self):
        self.json(self.PLUGIN, lambda p: p['skills'].remove('./skills/triage'))
        self.refused('manifest', self.PLUGIN)

    def test_an_extra_entry_is_refused(self):
        self.json(self.PLUGIN, lambda p: p['skills'].append('./skills/zeta'))
        self.refused('manifest', self.PLUGIN)

    def test_a_duplicate_entry_is_refused(self):
        self.json(self.PLUGIN, lambda p: p['skills'].append('./skills/triage'))
        self.refused('manifest', self.PLUGIN)

    def test_entries_are_sorted_by_name(self):
        self.json(self.PLUGIN, lambda p: p['skills'].reverse())
        self.refused('manifest', self.PLUGIN)

    def test_the_plugin_is_named_openwiz(self):
        self.json(self.PLUGIN, lambda p: p.update(name='wizskills'))
        self.refused('manifest', self.PLUGIN)

    def test_the_version_is_semver_without_a_v(self):
        self.json(self.PLUGIN, lambda p: p.update(version='v0.1.0'))
        self.refused('manifest', self.PLUGIN)

    def test_the_plugin_ships_no_hooks(self):
        self.json(self.PLUGIN, lambda p: p.update(hooks='./hooks.json'))
        self.refused('manifest', self.PLUGIN)

    def test_duplicate_json_keys_are_refused(self):
        path = self.root / self.PLUGIN
        path.write_text(path.read_text()[:-1] + ', "name": "other"}')
        self.refused('manifest', self.PLUGIN)

    def test_the_marketplace_is_named_wizskills(self):
        self.json(self.MARKET, lambda m: m.update(name='openwiz'))
        self.refused('manifest', self.MARKET)

    def test_the_marketplace_source_is_the_root(self):
        self.json(self.MARKET, lambda m: m['plugins'][0].update(source='./skills'))
        self.refused('manifest', self.MARKET)

    def test_a_repeated_version_must_agree(self):
        self.json(self.MARKET, lambda m: m['plugins'][0].update(version='0.2.0'))
        self.refused('manifest', self.MARKET)

    def test_a_missing_manifest_is_refused(self):
        (self.root / self.PLUGIN).unlink()
        self.refused('manifest', self.PLUGIN)


class Layout(Tree):
    def test_a_stray_file_in_skills_is_refused(self):
        write(self.root / 'skills/notes.txt', 'synthetic\n')
        self.refused('layout', 'skills/notes.txt')

    def test_a_folder_without_skill_md_is_refused(self):
        (self.root / 'skills/zeta/agents').mkdir(parents=True)
        self.refused('layout', 'skills/zeta/SKILL.md')

    def test_the_skills_readme_is_required(self):
        (self.root / 'skills/README.md').unlink()
        self.refused('layout', 'skills/README.md')


class Suites(Tree):
    def test_a_failing_suite_fails_the_check_after_every_suite_ran(self):
        write(self.root / 'skills/plan-graph/test/test-revision.sh',
              '#!/bin/sh\necho skills/plan-graph/test/test-revision.sh >> ran.txt\nexit 3\n')
        code, out = run(self.root)
        self.assertEqual(code, 1, out)
        self.assertEqual(ran(self.root), self.suites)
        self.assertIn('suite plan-graph: sh skills/plan-graph/test/test-revision.sh: fail', out)

    def test_a_failing_unittest_suite_fails_the_check(self):
        write(self.root / 'skills/image/tests/test_synthetic.py',
              'import unittest\n\n\nclass T(unittest.TestCase):\n'
              '    def test_no(self):\n        self.fail("synthetic")\n')
        code, out = run(self.root)
        self.assertEqual(code, 1, out)
        self.assertIn('suite image:', out)

    def test_a_missing_suite_fails_the_check(self):
        (self.root / 'skills/launch-fleet/scripts/test-grants.py').unlink()
        code, out = run(self.root)
        self.assertEqual(code, 1, out)
        self.assertIn('suite launch-fleet: python3 -I skills/launch-fleet/scripts/test-grants.py: missing', out)

    def test_a_unittest_folder_with_no_tests_fails_the_check(self):
        (self.root / 'skills/hill-climb/tests/test_synthetic.py').unlink()
        code, out = run(self.root)
        self.assertEqual(code, 1, out)
        self.assertIn('suite hill-climb:', out)

    def test_a_standalone_refusal_fails_the_check(self):
        write(self.root / 'check/standalone.py',
              'import sys\nprint(\'{"rule":"standalone.read","file":"skills/triage/x.py","line":1}\')\n'
              'sys.exit(1)\n')
        code, out = run(self.root)
        self.assertEqual(code, 1, out)
        self.assertIn('standalone: fail', out)
        self.assertEqual(ran(self.root), self.suites)

    def test_the_standalone_check_is_called_with_tree(self):
        write(self.root / 'check/standalone.py',
              'import json, sys\nopen("standalone-args.json", "w").write(json.dumps(sys.argv[1:]))\n')
        code, out = run(self.root)
        self.assertEqual(code, 0, out)
        args = json.loads((self.root / 'standalone-args.json').read_text())
        self.assertEqual(args[0], '--tree')
        self.assertEqual(len(args), 2)
        self.assertEqual(Path(args[1]).resolve(), self.root.resolve())

    def test_a_missing_standalone_check_fails_the_check(self):
        (self.root / 'check/standalone.py').unlink()
        code, out = run(self.root)
        self.assertEqual(code, 1, out)
        self.assertIn('standalone: missing', out)

    def test_the_check_takes_no_arguments(self):
        done = subprocess.run([sys.executable, 'check/run.py', '--skip'], cwd=self.root,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(ran(self.root), [])


class Inventory(unittest.TestCase):
    def test_suites_are_ci_select_skills_list_without_closedwiz_tools(self):
        spec = importlib.util.spec_from_file_location('ci_skills', SOURCE / 'ci/select/skills.py')
        ci = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ci)
        expected = {name: [c for c in commands if c != CLOSEDWIZ_ONLY]
                    for name, commands in ci.SUITES.items()}
        self.assertEqual(load_run().SUITES, expected)
        self.assertEqual(sorted(expected), sorted(SUITE_SKILLS))


class Workflow(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_runs_the_check_on_every_push_and_pull_request(self):
        self.assertRegex(self.text, r'(?m)^on:\n  push:\n  pull_request:\n(?!  \S)')
        self.assertRegex(self.text, r'(?m)^        run: python3 check/run\.py$')

    def test_is_read_only_with_no_secret(self):
        self.assertRegex(self.text, r'(?m)^permissions:\n  contents: read\n(?!  \S)')
        self.assertEqual(self.text.count('permissions:'), 1)
        self.assertNotRegex(self.text.lower(), r'secret|token|\$\{\{')
        self.assertIn('persist-credentials: false', self.text)
        for uses in re.findall(r'uses: (\S+)', self.text):
            self.assertRegex(uses, r'^[\w.-]+/[\w.-]+@[0-9a-f]{40}$')

    def test_needs_no_closedwiz_path(self):
        for name in ('closedwiz', 'jparker2006', 'tools/', 'ci/', 'private/',
                     '.github/actions', 'room-cli', 'cargo', 'apps/'):
            self.assertNotIn(name, self.text.lower())


if __name__ == '__main__':
    unittest.main()
