// Synthetic attachments and project references at the three public new-thread parser seams (#464, #636, #659, #677, #719, #723).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { isDeepStrictEqual } from 'node:util';

import { parseOptions, parsePreview, parseReport, parseStatus } from '../../src/newthread.ts';
import * as nt from '../support/newthread-synthetic.ts';

const body = { op_id: 'syn-1', text: 'synthetic', attachments: [], harness: 'codex', model: 'syn-model', effort: 'low' };
const defs = JSON.parse(readFileSync(new URL('../../../../contracts/new-thread.v1.schema.json', import.meta.url), 'utf8')).$defs;
const nameSchema = defs.prompt_attachment.properties.name;

const attachment = { id: 'syn-a', sha256: 'a'.repeat(64), size_bytes: 1, kind: 'file' as const, name: 'a.txt' };
const other = { ...attachment, id: 'syn-b' };
test("New-thread readers preserve attachment contracts and machine-neutral effect facts", async (t) => {
  for (const [name, proof] of [
    ['#719: caution constants match the contract in every new-thread parser', (t) => {
      const started = () => nt.start('thr_synthetic', 'started', body);
      const created = () => nt.report('prj_synthetic', body, nt.OUTCOMES.created('thr_synthetic'), started());
      const embedded = () => {
        const status: any = nt.status(body.op_id, created());
        status.result.report.start = started();
        return status;
      };
      const uncertain = () => nt.status(body.op_id, nt.report('prj_synthetic', body, nt.OUTCOMES.uncertain()));
      const label = defs.options.properties.label, reported = defs.reported_configuration.properties.label;
      const sites: [string, { const: string }, () => unknown, (json: unknown) => unknown, (v: any, x: unknown) => void][] = [
        ['offered options label', label, () => nt.options(), parseOptions, (v, x) => { v.label = x; }],
        ['unavailable options label', label, nt.noOptions, parseOptions, (v, x) => { v.label = x; }],
        ['report start label', reported, created, parseReport, (v, x) => { v.start.reported.label = x; }],
        ['recorded status start label', reported, () => nt.status(body.op_id, created()), parseStatus, (v, x) => { v.result.start.reported.label = x; }],
        ['recorded status embedded report start label', reported, embedded, parseStatus, (v, x) => { v.result.report.start.reported.label = x; }],
        ['recorded status observations text', defs.observations.properties.text, uncertain, parseStatus, (v, x) => { v.result.observations.text = x; }],
      ];
      const accepted: [string, boolean][] = [];
      for (const [site, rule, make, parse, set] of sites) {
        const exact = rule.const;
        assert.equal(typeof exact, 'string', `${site}: the contract fixes one string`);
        const control = make();
        set(control, exact);
        assert.deepEqual(parse(control), control, `${site}: the exact constant is accepted with every other field kept`);
        for (const [kind, value] of [['replacement', 'synthetic replacement'], ['leading space', ` ${exact}`], ['trailing space', `${exact} `], ['upper case', exact.toUpperCase()], ['empty', ''], ['null', null], ['number', 1], ['array', [exact]]] as const) {
          t.diagnostic(`#719: ${site} ${kind} is rejected by the schema and its new-thread parser`);
          assert.notDeepEqual(value, exact, 'contract verdict');
          const mutated = make();
          set(mutated, value);
          accepted.push([`${site}, ${kind}`, parse(mutated) !== null]);
        }
      }
      // Check every mutation even when one is accepted, so red records every one.
      assert.deepEqual(accepted, accepted.map(([name]) => [name, false]), 'one-field mutations at every caution');
    }],
    ['#677: project references match the contract in every new-thread parser', (t) => {
      const rule = defs.project_ref_value;
      // The whitespace set the contract's pattern lists: U+0085 is in it; U+FEFF, U+200B and U+180E are not.
      const spaces = [0x9, 0xa, 0xb, 0xc, 0xd, 0x20, 0x85, 0xa0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000];
      const cases: [string, string, boolean][] = [
        ...spaces.map((c): [string, string, boolean] => [`U+${c.toString(16).padStart(4, '0')} alone`, String.fromCodePoint(c), false]),
        ['empty', '', false],
        ['mixed whitespace', ' \t\n\u00a0\u3000', false],
        ['NUL alone', '\0', false],
        ['NUL prefix', '\0prj', false],
        ['NUL infix', 'prj\0bad', false],
        ['NUL suffix', 'prj\0', false],
        ['NUL before a trailing newline', 'prj\0\n', false],
        ['synthetic id', 'prj_synthetic', true],
        ['display name with suffix', 'Synthetic Project~abc123', true],
        ['Unicode name', 'Projet synthétique', true],
        ['padded', '  prj  ', true],
        ['multiline', '\nprj\n', true],
        ['U+FEFF', '\ufeff', true],
        ['U+200B', '\u200b', true],
        ['U+180E', '\u180e', true],
        ['U+0008', '\u0008', true],
      ];
      for (const [label, value, accepted] of cases) {
        const schemaAccepts = rule.type === 'string' && value.length >= rule.minLength && new RegExp(rule.pattern).test(value);
        assert.equal(schemaAccepts, accepted, `contract verdict for ${label}`);
        for (const kind of ['id', 'name'] as const) {
          t.diagnostic(`#677: ${kind} ${label} is ${accepted ? 'accepted' : 'rejected'} by the schema and every new-thread parser`);
          const project_ref = { kind, value };
          const preview = { ...nt.preview('prj_synthetic', body), project_ref };
          const report = { ...nt.report('prj_synthetic', body, nt.OUTCOMES.created('thr_synthetic')), project_ref };
          const status = nt.status(body.op_id, report);
          assert.deepEqual(
            [parsePreview(preview), parseReport(report), parseStatus(status)],
            accepted ? [preview, report, status] : [null, null, null],
            `preview, report, recorded status for ${kind} ${label}`,
          );
        }
      }
    }],
    ['#659:attachment uniqueness matches the contract in every new-thread parser', (t) => {
      for (const [label, attachments, accepted] of [
        ['omitted', undefined, true],
        ['one', [attachment], true],
        ['different id', [attachment, other], true],
        ['different hash', [attachment, { ...attachment, sha256: 'b'.repeat(64) }], true],
        ['different size', [attachment, { ...attachment, size_bytes: 2 }], true],
        ['different kind', [attachment, { ...attachment, kind: 'image' as const }], true],
        ['different name', [attachment, { ...attachment, name: 'b.txt' }], true],
        ['reversed unique list', [other, attachment], true],
        ['same object', [attachment, attachment], false],
        ['copied object', [attachment, { ...attachment }], false],
        ['reordered keys', [attachment, { name: attachment.name, kind: attachment.kind, size_bytes: attachment.size_bytes, sha256: attachment.sha256, id: attachment.id }], false],
        ['nonadjacent duplicate', [attachment, other, { ...attachment }], false],
      ] as const) {
        t.diagnostic(`#659: ${label} attachments match whole-object uniqueness in every new-thread parser`);
        for (const shape of [defs.preview, defs.report]) {
          const rule = shape.properties.attachments;
          assert.equal(rule.uniqueItems, true);
          const schemaAccepts = attachments === undefined || attachments.every((item, i) => !attachments.slice(0, i).some((prior) => isDeepStrictEqual(prior, item)));
          assert.equal(schemaAccepts, accepted, 'contract uniqueness verdict');
        }
        const fields = attachments === undefined ? {} : { attachments: [...attachments] };
        const preview = { ...nt.preview('prj_synthetic', body), ...fields };
        const report = { ...nt.report('prj_synthetic', body, nt.OUTCOMES.created('thr_synthetic')), ...fields };
        const status = nt.status(body.op_id, report);
        const parsed = [parsePreview(preview), parseReport(report), parseStatus(status)];
        assert.deepEqual(parsed.map((value) => value !== null), [accepted, accepted, accepted], 'preview, report, recorded status');
        if (accepted) assert.deepEqual(parsed, [preview, report, status], 'preserve attachment order and metadata');
      }
    }],
    ['#636: attachment cardinality matches the contract in every new-thread parser', (t) => {
      for (const { label, attachments, accepted } of [
        { label: 'omitted', attachments: undefined, accepted: true },
        { label: 'empty', attachments: [], accepted: false },
        { label: 'one', attachments: [{ id: 'syn-1', sha256: 'a'.repeat(64), size_bytes: 1, kind: 'file' as const, name: 'valid.txt' }], accepted: true },
      ]) {
        t.diagnostic(`#636: ${label} attachments match the contract's cardinality in every new-thread parser`);
        for (const shape of [defs.preview, defs.report]) {
          assert.equal(shape.required.includes('attachments'), false, 'attachments are optional');
          const rule = shape.properties.attachments;
          assert.equal(rule.type, 'array');
          assert.equal(rule.minItems, 1);
          assert.equal(attachments === undefined || attachments.length >= rule.minItems, accepted, 'contract cardinality verdict');
        }
        const fields = attachments === undefined ? {} : { attachments };
        const preview = { ...nt.preview('prj_synthetic', body), ...fields };
        const report = { ...nt.report('prj_synthetic', body, nt.OUTCOMES.created('thr_synthetic')), ...fields };
        const status = nt.status(body.op_id, report);
        assert.deepEqual(
          [parsePreview(preview) !== null, parseReport(report) !== null, parseStatus(status) !== null],
          [accepted, accepted, accepted],
          'preview, report, recorded status',
        );
      }
    }],
    ['#464: attachment names match the schema in every new-thread parser', (t) => {
      for (const [name, accepted] of [
        ['../x', false],
        ['.hidden', false],
        ['a/b', false],
        ['é.txt', false],
        ['-x', false],
        ['', false],
        ['a'.repeat(180), false],
        ['valid.txt', true],
        ['aA', true],
        ['aZ', true],
        ['Aa', true],
        ['_x', true],
        ['a'.repeat(179), true],
      ] as const) {
        t.diagnostic(`#464: attachment name ${JSON.stringify(name)} is ${accepted ? 'accepted' : 'rejected'} by the schema and every new-thread parser`);
        const schemaAccepts = nameSchema.type === 'string' && name.length >= nameSchema.minLength && name.length <= nameSchema.maxLength && new RegExp(nameSchema.pattern).test(name);
        assert.equal(schemaAccepts, accepted, 'contract verdict');
        const attachments = [{ id: 'syn-1', sha256: 'a'.repeat(64), size_bytes: 1, kind: 'file' as const, name }];
        const preview = { ...nt.preview('prj_synthetic', body), attachments };
        const report = { ...nt.report('prj_synthetic', body, nt.OUTCOMES.created('thr_synthetic')), attachments };
        const status = nt.status(body.op_id, report);
        // Check all three even when one parser fails, so red records every seam.
        assert.deepEqual(
          [parsePreview(preview), parseReport(report), parseStatus(status)],
          accepted ? [preview, report, status] : [null, null, null],
          'preview, report, recorded status',
        );
      }
    }],
    ['#723: report provider matches the schema in report and recorded status', (t) => {
      assert.deepEqual(defs.report.properties.provider, { type: ['string', 'null'] }, 'the contract: any string or null');
      assert.ok(defs.report.required.includes('provider'), 'the contract: required');
      const omitted = Symbol('omitted');
      for (const [label, value, accepted] of [
        ['omitted', omitted, false],
        ['undefined', undefined, false],
        ['number', 1, false],
        ['boolean', true, false],
        ['array', ['codex'], false],
        ['object', { name: 'codex' }, false],
        ['empty string', '', true],
        ['whitespace string', ' ', true],
        ['NUL string', '\0', true],
        ['nonempty string', 'syn-provider', true],
        ['null', null, true],
      ] as const) {
        t.diagnostic(`#723: provider ${label} is ${accepted ? 'accepted' : 'rejected'} by the schema, report and recorded status`);
        const report: any = nt.report('prj_synthetic', body, nt.OUTCOMES.created('thr_synthetic'));
        if (value === omitted) delete report.provider;
        else report.provider = value;
        const status = nt.status(body.op_id, report);
        // Check both even when one parser fails, so red records every seam.
        assert.deepEqual([parseReport(report), parseStatus(status)], accepted ? [report, status] : [null, null], 'report, recorded status');
      }
    }],
    ['#983: fixture effects are machine-neutral with unchanged kinds', (t) => {
      for (const [label, value, parse] of [
        ['preview', nt.preview('prj_synthetic', body), parsePreview],
        ['report', nt.report('prj_synthetic', body, nt.OUTCOMES.created('thr_synthetic')), parseReport],
      ] as const) {
        t.diagnostic(`#983: ${label} fixture uses machine-neutral effect text with unchanged kinds`);
        const parsed = parse(value);
        assert.ok(parsed, 'the fixture passes the public parser');
        assert.deepEqual(
          parsed.effects?.effects.filter((effect) => effect.kind === 'copies_env_files' || effect.kind === 'mac_stays_awake'),
          [
            { kind: 'copies_env_files', text: "copies the project's .env files from this computer" },
            { kind: 'mac_stays_awake', text: 'this computer must stay awake until the start is confirmed' },
          ],
        );
      }
    }],
  ] as const satisfies readonly (readonly [string, (context: import('node:test').TestContext) => void])[]) {
    t.diagnostic(name);
    await proof(t);
  }
});
