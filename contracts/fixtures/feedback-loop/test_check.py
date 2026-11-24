#!/usr/bin/env python3
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import check  # noqa: E402 -- imported after its folder joins sys.path


class Fixtures(unittest.TestCase):
    def test_the_fixtures_and_template_hold_and_cover_the_loop(self):
        self.assertEqual(check.check(ROOT), [])


def planted(edit):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel in (check.CONTRACT, check.FIXTURES, '.github/ISSUE_TEMPLATE/feedback.yml'):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            copy = shutil.copytree if (ROOT / rel).is_dir() else shutil.copyfile
            copy(ROOT / rel, root / rel)
        edit(root)
        return check.check(root)


def case(name, change):
    def edit(root):
        path = root / check.FIXTURES / f'{name}.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        change(data)
        path.write_text(json.dumps(data), encoding='utf-8')
    return edit


def template(old, new):
    def edit(root):
        path = root / '.github/ISSUE_TEMPLATE/feedback.yml'
        text = path.read_text(encoding='utf-8')
        assert old in text
        path.write_text(text.replace(old, new), encoding='utf-8')
    return edit


class PlantedBreaks(unittest.TestCase):

    def refused(self, edit, *expected):
        self.assertEqual(planted(edit), list(expected))

    def test_a_failed_criterion_never_goes_to_a_fleet(self):
        self.refused(case('triage-to-a-fleet', lambda d: d['input']['criteria'].update(no_instructions=False)),
                     'triage-to-a-fleet.json: outcome must be held', 'fixtures: no to a fleet case')

    def test_an_instruction_carrying_report_is_held(self):
        def send(d):
            d['input']['criteria']['no_instructions'] = True
            d['expect']['outcome'] = 'held'
        self.refused(case('triage-held-instruction', send), 'triage-held-instruction.json: outcome must be fleet')

    def test_the_brief_copies_no_link_or_code_from_the_report(self):
        def copy(d):
            d['input']['report']['body'] = 'See https://synthetic.example/x\n\n' + d['input']['report']['body']
            d['expect']['brief']['body'] = 'https://synthetic.example/x\n' + d['expect']['brief']['body']
        self.refused(case('triage-to-a-fleet', copy), 'triage-to-a-fleet.json: the brief copies a link or code from the report')

    def test_triage_posts_no_comment_on_the_report(self):
        self.refused(case('triage-held-too-big', lambda d: d['expect']['report_comments'].append('Thanks!')),
                     'triage-held-too-big.json: triage posts no comment on the report')

    def test_a_held_report_keeps_needs_triage(self):
        self.refused(case('triage-held-too-big', lambda d: d['expect'].update(report_labels=['feedback'])),
                     "triage-held-too-big.json: the report must be labelled exactly ['feedback', 'needs-triage']")

    def test_a_second_merge_posts_nothing(self):
        self.refused(case('landed-second-merge', lambda d: d['expect']['posts'].append([9101, 'x'])),
                     'landed-second-merge.json: posts must be []')

    def test_only_a_record_authors_landed_comment_counts(self):
        def forge(d):
            d['input']['issues']['9101']['comments'][0]['author'] = 'synthetic-user'
        self.refused(case('landed-second-merge', forge),
                     'landed-second-merge.json: posts must be [[9101, '
                     "'Landed: the fix for this report merged in openwizdev/OpenWiz#9202 and will ship in OpenWiz 9.4.2.']]",
                     'fixtures: no second merge case')

    def test_no_landed_comment_without_a_version_or_a_merge(self):
        self.refused(case('landed', lambda d: d['input']['issues']['9101'].update(milestone='next')),
                     'landed.json: posts must be []', 'fixtures: no landed case')
        self.refused(case('landed', lambda d: d['input']['pull_request'].update(merged=False)),
                     'landed.json: posts must be []', 'fixtures: no landed case')

    def test_the_landed_comment_follows_the_brief_link(self):
        self.refused(case('landed', lambda d: d['input']['pull_request'].update(closes=['Closes openwizdev/OpenWiz#9101'])),
                     'landed.json: posts must be []', 'fixtures: no landed case')

    def test_a_report_link_counts_only_from_a_record_author_and_last(self):
        self.refused(case('report-link-forged', lambda d: d['input']['issue'].update(author='synthetic-maintainer')),
                     'report-link-forged.json: report is 9101, the case expects None', 'fixtures: no forged link case')
        moved = 'Report: #9101\n\nKeep the approve button above the footer.'
        self.refused(case('report-link', lambda d: d['input']['issue'].update(body=moved)),
                     'report-link.json: report is None, the case expects 9101', 'fixtures: no report link case')

    def test_the_landed_comment_names_the_pull_request_in_full(self):
        self.refused(case('landed', lambda d: d['input']['pull_request'].update(repository='synthetic-org/WizSkills')),
                     'landed.json: posts must be []', 'fixtures: no landed case')

    def test_only_a_full_closing_line_reaches_the_destination(self):
        self.refused(case('landed', lambda d: d['input']['pull_request'].update(closes=['Closes #9106', 'Closes #9101'])),
                     'landed.json: posts must be []', 'fixtures: no landed case')

    def test_a_marker_counts_only_as_the_last_line(self):
        self.refused(case('not-a-report', lambda d: d['expect'].update(is_report=True)),
                     'not-a-report.json: is_report is False, the case expects True')

    def test_a_case_with_an_unknown_or_repeated_key_is_refused(self):
        self.refused(case('landed', lambda d: d['expect'].update(note='x')),
                     "landed.json: unreadable: a landed expectation must have exactly the keys ['posts']",
                     'fixtures: no landed case')

        def repeat(root):
            path = root / check.FIXTURES / 'landed.json'
            path.write_text('{"kind": "landed", ' + path.read_text(encoding='utf-8')[1:], encoding='utf-8')
        self.refused(repeat, 'landed.json: unreadable: a repeated key', 'fixtures: no landed case')
        self.refused(case('landed', lambda d: d['input']['pull_request'].update(merged='false')),
                     'landed.json: unreadable: merged is true or false and closes is a list of closing lines',
                     'fixtures: no landed case')

    def test_the_template_asks_only_for_public_words(self):
        log = '  - type: textarea\n    id: logs\n    attributes:\n      label: Logs\n      render: shell\n'
        fields = "{'type': 'textarea', 'id': 'logs', 'required': False}"
        found = planted(template('  - type: checkboxes', log + '  - type: checkboxes'))
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0], 'template: field logs asks for more than words')
        self.assertIn(fields, found[1])
        self.refused(template('Everything you write here is public: anyone can read it.', 'Tell us.'),
                     'template: the template must open with the public notice')
        self.refused(template('labels: [feedback]', 'labels: [bug]'),
                     "template: the template must be named 'Report a problem' and labelled exactly ['feedback']")
        found = planted(template('      value: "Everything', '      value: |\n        "Everything'))
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith('template: unreadable: unsupported YAML'))
        found = planted(template('          required: true', '          required: false'))
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith('template: the template fields must be exactly'))

    def test_the_template_keeps_the_approved_warning_and_confirmation(self):
        warning = 'Use only public words you choose to share. Do not paste prompts, transcripts, code, file paths, ' \
            'tokens, logs or screenshots of private work.'
        self.refused(template(warning, 'Paste private logs here.'),
                     'template: the template must carry exactly the approved warning')
        self.refused(template('Everything above is public words I chose to share.', 'I included my private logs.'),
                     'template: the public-words checkbox must confirm exactly the approved confirmation')
        second = '        - label: I agree.\n          required: true\n'
        self.refused(template('          required: true\n', '          required: true\n' + second),
                     'template: the public-words checkbox must confirm exactly the approved confirmation')

    def test_the_template_includes_optional_version_and_setup_fields(self):
        form = check.parse_yaml((ROOT / '.github/ISSUE_TEMPLATE/feedback.yml').read_text(encoding='utf-8'))
        ids = [(f.get('id'), f.get('type'), f.get('validations', {}).get('required') is True) for f in form['body']]
        self.assertEqual(ids, [
            (None, 'markdown', False),
            ('what-happened', 'textarea', True),
            ('expected', 'textarea', True),
            ('steps', 'textarea', False),
            ('version', 'input', False),
            ('setup', 'input', False),
            ('public-words', 'checkboxes', False),
        ])
        self.refused(template('    id: version\n', '    id: os-version\n'),
                     "template: the template fields must be exactly "
                     "[{'type': 'markdown', 'id': None, 'required': False}, "
                     "{'type': 'textarea', 'id': 'what-happened', 'required': True}, "
                     "{'type': 'textarea', 'id': 'expected', 'required': True}, "
                     "{'type': 'textarea', 'id': 'steps', 'required': False}, "
                     "{'type': 'input', 'id': 'version', 'required': False}, "
                     "{'type': 'input', 'id': 'setup', 'required': False}, "
                     "{'type': 'checkboxes', 'id': 'public-words', 'required': True}], "
                     "found [{'type': 'markdown', 'id': None, 'required': False}, "
                     "{'type': 'textarea', 'id': 'what-happened', 'required': True}, "
                     "{'type': 'textarea', 'id': 'expected', 'required': True}, "
                     "{'type': 'textarea', 'id': 'steps', 'required': False}, "
                     "{'type': 'input', 'id': 'os-version', 'required': False}, "
                     "{'type': 'input', 'id': 'setup', 'required': False}, "
                     "{'type': 'checkboxes', 'id': 'public-words', 'required': True}]")

    def _replace_facts_line(self, new_line):
        def edit(d):
            lines = d['input']['body'].split('\n')
            lines[-3] = new_line
            d['input']['body'] = '\n'.join(lines)
        return case('report-with-facts', edit)

    def _expect_facts_refused(self, edit):
        found = planted(edit)
        self.assertEqual(len(found), 2, found)
        self.assertTrue(found[0].startswith('report-with-facts.json: facts is None, the case expects '), found[0])
        self.assertEqual(found[1], 'fixtures: no facts case')

    def test_facts_line_refuses_unknown_key(self):
        self._expect_facts_refused(
            self._replace_facts_line('OpenWiz feedback facts {"v":1,"extra":"bad"}'))

    def test_facts_line_refuses_repeated_key(self):
        self._expect_facts_refused(
            self._replace_facts_line('OpenWiz feedback facts {"v":1,"kind":"bug","kind":"idea"}'))

    def test_facts_line_refuses_wrong_key_order(self):
        self._expect_facts_refused(
            self._replace_facts_line('OpenWiz feedback facts {"v":1,"area":"cli","kind":"bug"}'))

    def test_facts_line_refuses_value_outside_pattern_or_type(self):
        bad_lines = [
            'OpenWiz feedback facts {"v":2}',
            'OpenWiz feedback facts {"v":true}',
            'OpenWiz feedback facts {"kind":"bug"}',
            'OpenWiz feedback facts {"v":1,"kind":"feature"}',
            'OpenWiz feedback facts {"v":1,"area":"Launch_Fleet"}',
            'OpenWiz feedback facts {"v":1,"openwiz":"0.1"}',
            'OpenWiz feedback facts {"v":1,"skill":"0.4.0"}',
            'OpenWiz feedback facts {"v":1,"os":"freebsd"}',
            'OpenWiz feedback facts {"v":1,"arch":"riscv64"}',
            'OpenWiz feedback facts {"v":1,"model":"claude opus"}',
            'OpenWiz feedback facts {"v":1,"log_lines":41}',
            'OpenWiz feedback facts {"v":1,"redactions":10000}',
            'OpenWiz feedback facts {"v":1,"log_lines":true}',
            'OpenWiz feedback facts {"v": 1}',
            'OpenWiz feedback facts {"v":1,"host":"cl\u00f6ud"}',
        ]
        for line in bad_lines:
            with self.subTest(line=line):
                self._expect_facts_refused(self._replace_facts_line(line))

    def test_facts_line_refuses_wrong_place(self):
        def move_to_top(d):
            lines = d['input']['body'].split('\n')
            facts = lines[-3]
            d['input']['body'] = facts + '\n\n' + '\n'.join(lines[:-4]) + '\n\n' + lines[-1]
        self._expect_facts_refused(case('report-with-facts', move_to_top))

        def no_blank_above(d):
            lines = d['input']['body'].split('\n')
            del lines[-4]
            d['input']['body'] = '\n'.join(lines)
        self._expect_facts_refused(case('report-with-facts', no_blank_above))

        def no_marker(d):
            lines = d['input']['body'].split('\n')
            d['input']['labels'] = ['feedback']
            d['input']['body'] = '\n'.join(lines[:-2])
        self._expect_facts_refused(case('report-with-facts', no_marker))

    def test_facts_line_refuses_two_facts_lines(self):
        def duplicate(d):
            lines = d['input']['body'].split('\n')
            d['input']['body'] = 'OpenWiz feedback facts {"v":1}\n\n' + '\n'.join(lines)
        self._expect_facts_refused(case('report-with-facts', duplicate))

    def test_facts_line_refuses_line_over_1024_characters(self):
        long_facts = 'OpenWiz feedback facts {"v":1,"openwiz":"0.0.' + ('0' * 1000) + '"}'
        self.assertGreater(len(long_facts), 1024)
        self._expect_facts_refused(self._replace_facts_line(long_facts))

    def test_facts_line_refuses_private_looking_values(self):
        bad_lines = [
            'OpenWiz feedback facts {"v":1,"model":"192.168.1.1"}',
            'OpenWiz feedback facts {"v":1,"model":"ghp_synthetic000000"}',
            'OpenWiz feedback facts {"v":1,"model":"sk-synthetic000000"}',
            'OpenWiz feedback facts {"v":1,"model":"thr_synthetic123"}',
        ]
        for line in bad_lines:
            with self.subTest(line=line):
                self._expect_facts_refused(self._replace_facts_line(line))

    def test_facts_line_refuses_log_counts_without_log_section_or_with_wrong_count(self):
        def strip_log_keep_log_lines(d):
            d['input']['body'] = (
                'What happened:\nThe approve button sits under the footer.\n\n'
                'OpenWiz feedback facts {"v":1,"log_lines":0}\n\n'
                'OpenWiz feedback operation 3f2a9c4e1b7d40a6958e0c2d7b1a4f63'
            )
        self._expect_facts_refused(case('report-with-facts', strip_log_keep_log_lines))

        def strip_log_keep_redactions(d):
            d['input']['body'] = (
                'What happened:\nThe approve button sits under the footer.\n\n'
                'OpenWiz feedback facts {"v":1,"redactions":0}\n\n'
                'OpenWiz feedback operation 3f2a9c4e1b7d40a6958e0c2d7b1a4f63'
            )
        self._expect_facts_refused(case('report-with-facts', strip_log_keep_redactions))

        self._expect_facts_refused(
            self._replace_facts_line('OpenWiz feedback facts {"v":1,"log_lines":3,"redactions":2}'))


if __name__ == '__main__':
    unittest.main()
