import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Session } from '../envelope.ts';
import { factText } from '../present.ts';
import type { LaunchProject } from './Launcher.tsx';
import { CloseIcon, FileIcon, HomeIcon, FleetsIcon, PlusIcon, SearchIcon, SessionsIcon } from './Icons.tsx';
import { PlanIcon } from './PlanGraph.tsx';
import { Marker } from './Status.tsx';

export function CommandTrigger({ compact = false, onOpen }: { compact?: boolean; onOpen: () => void }) {
  return <button type="button" className={`command-trigger${compact ? ' compact' : ''}`} aria-label={compact ? 'Search or jump to…' : undefined} aria-haspopup="dialog" aria-keyshortcuts="Meta+K Control+K /" onClick={onOpen}>
    <SearchIcon /><span>Search or jump to…</span>{compact ? null : <kbd>⌘K</kbd>}
  </button>;
}

type Props = {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  sessions: Session[];
  projects: LaunchProject[];
  onHome: () => void;
  onFirstHour: () => void;
  onCockpit: () => void;
  onPlan: () => void;
  onSessions: () => void;
  onFleets: () => void;
  onSession: (id: string) => void;
  onProject: (project: LaunchProject) => void;
};

/** Navigation uses only the already listed snapshot and the app's existing handlers. */
export function CommandNavigation(props: Props) {
  const { open, onOpen } = props;
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      const target = event.target;
      const typing = target instanceof HTMLElement && (target.isContentEditable || !!target.closest('input, textarea, select, [role="textbox"], [role="combobox"]'));
      const command = (event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 'k';
      const slash = event.key === '/' && !event.metaKey && !event.ctrlKey && !event.altKey && !typing;
      if (!command && !slash) return;
      event.preventDefault();
      if (!event.repeat && !open) onOpen();
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, [open, onOpen]);
  // A phone thread is already a native modal. Mount inside it so its inert
  // background and top layer never hide the command dialog or its input.
  return open ? createPortal(<CommandDialog {...props} />, document.querySelector('dialog:modal') ?? document.body) : null;
}

function CommandDialog({ onClose, sessions, projects, onHome, onFirstHour, onCockpit, onPlan, onSessions, onFleets, onSession, onProject }: Props) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const release = useRef<(() => void) | null>(null);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(0);
  const items = [
    { key: 'home', label: 'Go to Home', icon: <HomeIcon />, status: null, go: onHome },
    { key: 'first-hour', label: 'Go to First hour', icon: <FileIcon />, status: null, go: onFirstHour },
    { key: 'sessions', label: 'Go to Sessions', icon: <SessionsIcon />, status: null, go: onSessions },
    { key: 'fleets', label: 'Go to Fleets', icon: <FleetsIcon />, status: null, go: onFleets },
    { key: 'plan', label: 'Go to Plan', icon: <PlanIcon />, status: null, go: onPlan },
    { key: 'cockpit', label: 'Go to Cockpit', icon: <FleetsIcon />, status: null, go: onCockpit },
    ...projects.map((project) => ({ key: `project:${project.id}`, label: `New thread in ${factText(project.name)}${project.suffix === null ? '' : ` · ${project.suffix}`}`, icon: <PlusIcon />, status: null, go: () => onProject(project) })),
    ...sessions.map((session) => ({ key: `session:${session.id}`, label: factText(session.title), icon: null, status: <Marker status={session.status} />, go: () => onSession(session.id) })),
  ].filter((item) => item.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const active = Math.min(selected, Math.max(0, items.length - 1));
  const close = () => {
    release.current?.();
    onClose();
  };
  useEffect(() => {
    const element = root.current;
    const parent = element?.parentElement;
    if (!element || !parent) return;
    const from = document.activeElement;
    const siblings = Array.from(parent.children).filter((child): child is HTMLElement => child instanceof HTMLElement && child !== element);
    const previous = siblings.map((el) => el.inert);
    siblings.forEach((el) => { el.inert = true; });
    const alreadyLocked = document.body.classList.contains('command-open');
    document.body.classList.add('command-open');
    input.current?.focus();
    const containFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && !element.contains(event.target)) input.current?.focus();
    };
    document.addEventListener('focusin', containFocus);
    let released = false;
    const restore = () => {
      if (released) return;
      released = true;
      document.removeEventListener('focusin', containFocus);
      siblings.forEach((el, i) => { el.inert = previous[i] ?? false; });
      if (!alreadyLocked) document.body.classList.remove('command-open');
      if (from instanceof HTMLElement && from.isConnected) from.focus({ preventScroll: true });
    };
    release.current = restore;
    return restore;
  }, []);
  useEffect(() => {
    document.getElementById(`${id}-option-${active}`)?.scrollIntoView({ block: 'nearest' });
  }, [active, id, query]);

  return <div ref={root} className="command-backdrop" onClick={(event) => { if (event.target === event.currentTarget) close(); }}
    onKeyDown={(event) => {
      // Keep Escape and composer shortcuts inside this dialog, including when
      // it is portalled into the existing phone sheet.
      event.stopPropagation();
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') event.preventDefault();
      if (event.key === 'Escape') { event.preventDefault(); close(); }
      if (event.key === 'Tab') {
        event.preventDefault();
        const button = root.current?.querySelector('button');
        if (document.activeElement === input.current) button?.focus();
        else input.current?.focus();
      }
    }}>
    <div className="command-dialog" role="dialog" aria-modal="true" aria-label="Search or jump to…">
      <div className="command-input-row">
        <SearchIcon />
        <label className="command-label" htmlFor={`${id}-input`}>Search navigation</label>
        <input ref={input} id={`${id}-input`} role="combobox" aria-autocomplete="list" aria-expanded="true" aria-controls={`${id}-results`}
          aria-activedescendant={items.length ? `${id}-option-${active}` : undefined} autoComplete="off" spellCheck={false}
          placeholder="Search or jump to…" value={query} onChange={(event) => { setQuery(event.target.value); setSelected(0); }}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing) return;
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault();
              setSelected(items.length ? (active + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length : 0);
            }
            if (event.key === 'Enter') {
              event.preventDefault();
              const item = items[active];
              if (item && !event.repeat) { close(); item.go(); }
            }
          }} />
        <button type="button" className="sheet-x" aria-label="Close search" onClick={close}><CloseIcon /></button>
      </div>
      <div className="command-results" id={`${id}-results`} role="listbox" aria-label="Navigation results">
        {items.map((item, index) => <div key={item.key} id={`${id}-option-${index}`} role="option" aria-selected={index === active}
          className="command-option" onPointerMove={() => setSelected(index)} onMouseDown={(event) => event.preventDefault()} onClick={() => { close(); item.go(); }}>
          {item.icon}<bdi className="command-title">{item.label}</bdi>{item.status}<span className="command-enter" aria-hidden="true">↵</span>
        </div>)}
      </div>
      {items.length === 0 ? <p className="command-empty" role="status">No matching destinations</p> : null}
      <div className="command-footer"><span>Jump to a view or thread</span><span>↑ ↓ to move · Enter to open · Esc to close</span></div>
    </div>
  </div>;
}
