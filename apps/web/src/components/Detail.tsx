import { CommandTrigger } from './CommandNavigation.tsx';
import { BackIcon, CloseIcon } from './Icons.tsx';
// The details of one session, as `show` returns them: a modal bottom sheet on
// phones, a side panel on desktop (≥ 900 px) (V9). Its controls are Close and,
// under the final output, the composer (#9). Since #12 the same panel and sheet
// hold the launcher instead, when a project's New thread is pressed: one
// dialog, never a second (U14).

import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';

import type { Envelope, SessionView } from '../envelope.ts';
import { ageText, boundedText, clockText, factText, unknownText } from '../present.ts';
import type { Composers } from '../composer.ts';
import type { Launchers } from '../launcher.ts';
import type { Uploads } from '../attachments.ts';
import type { DetailState } from '../viewer.ts';
import { Composer } from './Composer.tsx';
import { Launcher } from './Launcher.tsx';
import type { LaunchProject } from './Launcher.tsx';
import { ConnectionGlyph, CoverageChip, Marker, Notice } from './Status.tsx';

const WIDE = '(min-width: 900px)';

function useWide(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const q = window.matchMedia(WIDE);
      q.addEventListener('change', onChange);
      return () => q.removeEventListener('change', onChange);
    },
    () => window.matchMedia(WIDE).matches,
    () => false,
  );
}

function Fields({ envelope, stale, now }: { envelope: Envelope<SessionView>; stale: boolean; now: Date }) {
  const { session: s, final_output: out, reported_error: err } = envelope.data;
  const location = !('known' in s.location)
    ? unknownText(s.location.unknown)
    : s.location.known.kind === 'cloud'
      ? 'cloud'
      : `local on ${factText(s.location.known.machine)}`;
  const purpose = !('known' in s.recap)
    ? unknownText(s.recap.unknown)
    : s.recap.known.kind === 'no_recap_yet'
      ? 'no recap yet'
      : boundedText(s.recap.known.text, s.recap.known.truncated);
  const config = s.reported_configuration;
  return (
    <>
      <header className="thread-header">
        <div className="thread-heading">
          <dl className="thread-status">
            <dt>status</dt>
            <dd data-field="status"><Marker status={s.status} /></dd>
          </dl>
          <h2 id="detail-title" className="disp s"><bdi>{factText(s.title)}</bdi></h2>
        </div>
        <dl className="kv thread-meta">
          <dt>{s.group.kind === 'project' ? 'project' : 'ungrouped'}</dt>
          <dd data-field="group"><bdi>{s.group.kind === 'project' ? factText(s.group.name) : s.group.reason}</bdi></dd>
          <dt>provider</dt>
          <dd data-field="provider"><bdi>{factText(s.provider)}</bdi></dd>
          <dt>reported config</dt>
          <dd data-field="configuration"><span className="thread-meta-item">model <bdi>{factText(config.model)}</bdi></span><span className="thread-meta-item"> · effort <bdi>{factText(config.effort)}</bdi></span></dd>
          <dt>location</dt>
          <dd data-field="location"><bdi>{location}</bdi></dd>
          <dt>age</dt>
          <dd data-field="age">{'known' in s.age_ms ? ageText(s.age_ms.known) : unknownText(s.age_ms.unknown)}</dd>
          {s.started_at === undefined ? null : (
            <>
              <dt>started</dt>
              <dd data-field="started">{'known' in s.started_at ? clockText(s.started_at.known, now) : unknownText(s.started_at.unknown)}</dd>
            </>
          )}
        </dl>
        <p className="thread-id"><code>{s.id}</code></p>
      </header>
      <dl className="thread-purpose">
        <dt>Purpose</dt>
        <dd data-field="purpose"><bdi>{purpose}</bdi></dd>
      </dl>
      {envelope.gaps.length > 0 ? (
        <>
          <p className="sec">
            {envelope.gaps.length} {envelope.gaps.length === 1 ? 'gap' : 'gaps'}
          </p>
          <ul className="gaps" data-part="detail-gaps">
            {envelope.gaps.map((g, i) => (
              <li key={i}>
                <bdi>{`${g.kind}${g.subject === null ? '' : ` · ${g.subject}`} · ${g.detail}`}</bdi>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <section className="thread-reply">
        <h3 className="sec">Latest reply</h3>
        <div data-field="final-output">
          {!('known' in out) ? (
            unknownText(out.unknown)
          ) : out.known.kind === 'no_final_output_yet' ? (
            'no final output yet'
          ) : (
            <>
              <pre className="out" dir="auto">
                {boundedText(out.known.text, out.known.truncated)}
              </pre>
              {out.known.truncated ? (
                <span className="mod" data-part="final-output-truncated">
                  truncated
                </span>
              ) : null}
            </>
          )}
        </div>
      </section>
      <div className="thread-read">
        <CoverageChip envelope={envelope} now={now} detail />
        {stale ? <span className="status-chip" data-part="detail-stale"><ConnectionGlyph connection="stale" /> stale</span> : null}
        <dl className="kv">
          <dt>reported error</dt>
          <dd data-field="reported-error"><bdi>{!('known' in err) ? unknownText(err.unknown) : err.known === null ? 'none' : boundedText(err.known.text, err.known.truncated)}</bdi></dd>
        </dl>
      </div>
    </>
  );
}

/** The launcher's part of the panel: its project, and what it needs from the page. */
export type LaunchPanel = {
  project: LaunchProject;
  launchers: Launchers;
  uploads: Uploads;
  listed: (id: string) => boolean;
  snapshotAt: number;
  onShowThread: (id: string) => void;
};

export function Detail({
  detail,
  launch,
  listed,
  stale,
  now,
  composers,
  uploads,
  onClose,
  onSearch,
}: {
  detail: DetailState | null;
  /** The launcher, when a project's New thread was pressed: it takes the panel's place of a session's details. */
  launch: LaunchPanel | null;
  listed: boolean;
  stale: boolean;
  now: Date;
  composers: Composers;
  uploads: Uploads;
  onClose: () => void;
  onSearch: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const restoreClose = useRef(false);
  // Loading and loaded reading areas share the same header controls. Preserve
  // Close's focus when the loaded composer replaces the loading area.
  const setCloseButton = useCallback((button: HTMLButtonElement | null) => {
    if (button === null) restoreClose.current = document.activeElement === closeButton.current;
    closeButton.current = button;
    if (button && restoreClose.current) {
      restoreClose.current = false;
      button.focus({ preventScroll: true });
    }
  }, []);
  const switching = useRef(false);
  const loadedFor = useRef<string | null>(null);
  const shownFor = useRef<string | null>(null);
  const wide = useWide();
  const id = launch ? `launch:${launch.project.id}` : (detail?.id ?? null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    // Reopening the same detail for a layout change must keep its active control.
    const active = d.open && shownFor.current === id && d.contains(document.activeElement) ? document.activeElement : null;
    shownFor.current = id;
    if (id === null) {
      if (d.open) d.close();
      return;
    }
    if (!d.open || d.matches(':modal') !== !wide) {
      if (d.open) {
        switching.current = true;
        d.close();
      }
      if (wide) d.show();
      else d.showModal();
    }
    if (active instanceof HTMLElement) {
      active.focus();
      active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    } else closeButton.current?.focus();
    performance.clearMarks('detail-shown');
    performance.mark('detail-shown');
  }, [id, wide]);

  useEffect(() => {
    if (id === null || launch) loadedFor.current = null;
    else if (detail?.last && loadedFor.current !== id) {
      loadedFor.current = id;
      performance.clearMarks('detail-loaded');
      performance.mark('detail-loaded');
    }
  }, [id, detail?.last, launch]);

  const sheetHead = (
    <header className="sheet-head">
      <p className="sheet-cmd">{launch ? 'New thread' : 'Sessions'}</p>
      <CommandTrigger compact onOpen={onSearch} />
      <button ref={setCloseButton} type="button" className="sheet-x" aria-label="Sessions — close panel" onClick={() => ref.current?.close()}>
        <span className="sheet-back-icon"><BackIcon /></span>
        <span className="sheet-back-label">Sessions</span>
        {!launch ? <span className="thread-close-icon"><CloseIcon /></span> : null}
      </button>
    </header>
  );

  return (
    <dialog
      ref={ref}
      className={launch ? 'sheet' : 'sheet thread-sheet'}
      data-part="detail"
      data-session-id={launch ? undefined : (detail?.id ?? undefined)}
      data-launch={launch ? launch.project.id : undefined}
      aria-labelledby={launch ? undefined : detail?.last ? 'detail-title' : undefined}
      aria-label={launch ? 'New thread' : detail?.last ? undefined : 'Session details'}
      onClose={() => {
        if (switching.current) {
          switching.current = false;
          return;
        }
        onClose();
      }}
      onKeyDown={(e) => {
        // A modal sheet closes on Escape by itself; the side panel is not modal.
        if (e.key === 'Escape' && !e.currentTarget.matches(':modal')) {
          e.preventDefault();
          e.currentTarget.close();
        }
      }}
    >
      <div className="sheet-grab" aria-hidden="true" />
      {launch ? sheetHead : null}
      {launch ? (
        <Launcher key={launch.project.id} project={launch.project} launchers={launch.launchers} uploads={launch.uploads} listed={launch.listed} snapshotAt={launch.snapshotAt} onShowThread={launch.onShowThread} />
      ) : detail ? (
        detail.last ? (
          <Composer key={detail.id} id={detail.id} listed={listed} snapshotAt={detail.last.receivedAt} composers={composers} uploads={uploads}>
            {sheetHead}
            {!listed ? <p className="tag dashed" data-part="no-longer-listed">no longer listed on this page</p> : null}
            {detail.failure ? <Notice failure={detail.failure} lastGoodAt={detail.last.envelope.freshness.snapshot_at} now={now} /> : null}
            <Fields envelope={detail.last.envelope} stale={stale} now={now} />
          </Composer>
        ) : (
          <div className="thread-scroll" tabIndex={-1}>
            {sheetHead}
            {!listed ? <p className="tag dashed" data-part="no-longer-listed">no longer listed on this page</p> : null}
            {detail.failure ? <Notice failure={detail.failure} lastGoodAt={null} now={now} /> : <p className="meta">reading…</p>}
          </div>
        )
      ) : null}
    </dialog>
  );
}
