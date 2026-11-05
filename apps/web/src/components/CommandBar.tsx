// The cockpit's command bar (0.0.10 T4, #537), docked at the bottom of the
// page: the controller's words over the page's own data (src/command.ts).
//
// It is not the ⌘K dialog (CommandNavigation.tsx), which only navigates and
// keeps `/` and ⌘K: this bar takes focus on a click, a tap, Tab or `:`. It
// never sends: `y` and `approve` open the open item's Yes in its row, as
// pressing Yes would, and only the row's Send sends (twice for a risky item).
// History stays in this page's memory: it is never stored or sent.

import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';

import { choiceOf, itemStorage, readRecord } from '../cockpit.ts';
import type { Cockpit } from '../cockpit.ts';
import { bindingLine, crumbs, follow, run, TOP } from '../command.ts';
import type { Context, Line, Outcome, Scope } from '../command.ts';
import { browserStorage } from '../composer.ts';
import { CloseIcon } from './Icons.tsx';
import { StatusGlyph } from './StatusMark.tsx';

const SHOWN_LINES = 4;
const HISTORY = 50;

/**
 * Why an item's own answer record (src/cockpit.ts's per-item storage) keeps
 * `y` from opening a new answer for `binding`, as its row decides: an answer
 * made for this binding, or one for an earlier version whose result isn't
 * known. A settled answer to an earlier version doesn't: the row offers the
 * new proposal.
 */
function answered(key: string, binding: string): string | null {
  const rec = readRecord(itemStorage(browserStorage(), key));
  if (rec === null) return null;
  if (rec.binding === binding) return `already has an answer (${choiceOf(rec.text)} · ${rec.phase === 'pending' ? 'its result isn’t known yet' : rec.phase})`;
  return rec.phase === 'pending' ? 'has an unresolved answer to an earlier version of it' : null;
}

/** The chips: read-only words run at once; `cd`, numbers and `y` only fill the input, so Enter stays the owner's. */
const CHIPS: readonly { word: string; label: string; runs: boolean }[] = [
  { word: 'ls', label: 'ls', runs: true },
  { word: 'cd ', label: 'cd', runs: false },
  { word: 'cd ..', label: 'cd ..', runs: true },
  { word: 'next', label: 'next', runs: true },
  { word: 'blockers', label: 'blockers', runs: true },
  { word: '', label: '1–9', runs: false },
  { word: 'y', label: 'y', runs: false },
];

export type BarProps = {
  ctx: Omit<Context, 'answered'>;
  /** The scope's project left the read: the bar goes back to the top and says so. */
  lost: boolean;
  onOutcome: (o: Outcome) => void;
};

export function CommandBar({ ctx, lost, onOutcome }: BarProps) {
  const [value, setValue] = useState('');
  const [lines, setLines] = useState<Line[]>([]);
  const history = useRef<string[]>([]);
  const recall = useRef<number | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  const full: Context = { ...ctx, answered };

  const say = (line: Line) => setLines((was) => [...was, line].slice(-SHOWN_LINES));
  const submit = (text: string) => {
    const typed = text.trim();
    if (typed !== '' && history.current[history.current.length - 1] !== typed) history.current = [...history.current, typed].slice(-HISTORY);
    recall.current = null;
    setValue('');
    const o = run(text, full);
    if (o.line) say(o.line);
    onOutcome(o);
  };

  // `:` outside a text field focuses the bar; `/` and ⌘K stay the navigation dialog's.
  useEffect(() => {
    const key = (e: globalThis.KeyboardEvent) => {
      const t = e.target;
      const typing = t instanceof HTMLElement && (t.isContentEditable || !!t.closest('input, textarea, select, [role="textbox"], [role="combobox"], dialog'));
      if (e.key !== ':' || e.metaKey || e.ctrlKey || e.altKey || typing || e.repeat) return;
      e.preventDefault();
      input.current?.focus();
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, []);

  // The scope's project left the read: back to the top, said once.
  useEffect(() => {
    if (!lost) return;
    say({ input: '', tone: 'refused', text: 'Back at the top: the project you were in isn’t in this read any more.', items: [] });
    onOutcome({ line: null, scope: TOP, open: null });
  }, [lost]);

  // The open item's binding, followed on every snapshot and clock tick: once lost, it stays lost (review 1).
  const followed = follow(full);
  useEffect(() => {
    if (followed !== ctx.open) onOutcome({ line: null, open: followed });
  });

  // The item the bar opened comes into view when it is hidden: at the top, never under the docked bar.
  const openKey = ctx.open?.key ?? null;
  useEffect(() => {
    const row = openKey === null ? null : document.querySelector('[data-part=ck-needs-you] li[data-open]');
    const dock = document.querySelector('[data-part=command-bar]');
    if (!row || !dock) return;
    const r = row.getBoundingClientRect();
    if (r.top < 0 || r.bottom > dock.getBoundingClientRect().top) row.scrollIntoView({ block: 'start' });
  }, [openKey]);

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (!e.repeat && !e.nativeEvent.isComposing) submit(value);
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      input.current?.blur();
      return;
    }
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    const h = history.current;
    if (h.length === 0) return;
    e.preventDefault();
    const at = recall.current ?? h.length;
    const to = e.key === 'ArrowUp' ? Math.max(0, at - 1) : at + 1;
    recall.current = to >= h.length ? null : to;
    setValue(to >= h.length ? '' : (h[to] ?? ''));
  };

  const bound = bindingLine(value, full);
  return (
    <section className="ck-bar" data-part="command-bar" aria-label="Command bar">
      <ol className="ck-bar-out" data-part="command-output" aria-live="polite">
        {lines.map((l, i) => (
          <li key={`${lines.length - i}:${l.input}`} className={`ck-bar-line is-${l.tone}`} data-tone={l.tone}>
            {l.input !== '' ? <span className="ck-bar-echo"><bdi>{l.input}</bdi></span> : <span className="ck-bar-echo" aria-hidden="true" />}
            <span className="ck-bar-said">
              {l.tone === 'refused' ? <span className="ck-bar-mark" aria-hidden="true"><StatusGlyph tier="t5" /></span> : null}
              <span className="ck-bar-text" data-part="said"><bdi>{l.text}</bdi></span>
              {l.items.length > 0 ? <ul className="ck-bar-items">{l.items.map((it, j) => <li key={j}><bdi>{it}</bdi></li>)}</ul> : null}
            </span>
          </li>
        ))}
      </ol>
      {bound !== null ? (
        <p id="ck-bind" className="ck-bind" data-part="binding"><span className="ck-bind-mark" aria-hidden="true"><StatusGlyph tier="t1" /></span><bdi>{bound}</bdi></p>
      ) : null}
      <div className="ck-bar-field">
        <svg className="icon ck-bar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m8 7 5 5-5 5M14 17h4" /></svg>
        <input
          ref={input}
          type="text"
          className="ck-bar-input"
          data-part="command-input"
          aria-label="Command"
          aria-keyshortcuts=":"
          aria-describedby={bound !== null ? 'ck-bind' : undefined}
          placeholder="Type a command"
          autoComplete="off"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="go"
          maxLength={400}
          value={value}
          onChange={(e) => {
            recall.current = null;
            setValue(e.target.value);
          }}
          onKeyDown={onKeyDown}
          onPaste={(e) => {
            // The field strips line breaks before onChange, so pasted lines are judged here, on the raw text:
            // one bad command, never run, and nothing inserted (PR #1708's review, R1).
            const pasted = e.clipboardData.getData('text');
            if (!/[\r\n]/.test(pasted)) return;
            e.preventDefault();
            const o = run(pasted, full);
            if (o.line) say(o.line);
          }}
        />
        <span className="ck-bar-hint" aria-hidden="true">↵ run</span>
      </div>
      <div className="ck-bar-chips" data-part="command-chips">
        {CHIPS.map((chip) => (
          <button
            key={chip.label}
            type="button"
            className="ck-chip"
            aria-label={chip.runs ? `Run ${chip.word}` : chip.word === '' ? '1–9: type an item number' : `Type ${chip.word.trim()}`}
            onClick={() => {
              if (chip.runs) submit(chip.word);
              else {
                setValue(chip.word);
                input.current?.focus();
              }
            }}
          >
            {chip.label}
          </button>
        ))}
      </div>
    </section>
  );
}

/** The scope's breadcrumb, at the top of the page: Cockpit › Atlas › #901, with a clear button. */
export function ScopeCrumbs({ c, scope, onClear }: { c: Cockpit; scope: Scope; onClear: () => void }) {
  const parts = crumbs(c, scope);
  if (parts.length === 0) return null;
  return (
    <nav className="ck-crumbs" data-part="scope" aria-label="Scope">
      <ol>
        <li>Cockpit</li>
        {parts.map((p, i) => <li key={i} aria-current={i === parts.length - 1 ? 'location' : undefined}>{p.startsWith('#') ? <span className="id">{p}</span> : <bdi>{p}</bdi>}</li>)}
      </ol>
      <button type="button" className="btn quiet ck-crumbs-clear" aria-label="Clear the scope" onClick={onClear}><CloseIcon /></button>
    </nav>
  );
}
