// #2292: the owner's feedback handoff and the OpenWiz share, on the Home
// screen (contracts/feedback.v1.md). The owner writes only what they choose to
// make public, previews the exact text, and presses copy: the clipboard is
// written once, with those bytes. Nothing is sent, stored or collected here;
// the owner's own agent previews the issue and asks for a yes before creating
// it. Copied, sent and acknowledged are three different things, shown apart.
import { useState, useSyncExternalStore } from 'react';

import { StatusGlyph } from './StatusMark.tsx';
import { Copier, DESTINATION, feedbackProblem, handoffText, shareProblem, shareText } from '../feedback.ts';
import type { Clipboard, Copy } from '../feedback.ts';

const browserClipboard = (): Clipboard | null => (typeof navigator !== 'undefined' && navigator.clipboard ? navigator.clipboard : null);

function useCopier(): [Copier, Copy] {
  const [copier] = useState(() => new Copier(browserClipboard()));
  return [copier, useSyncExternalStore(copier.subscribe, copier.snapshot, copier.snapshot)];
}

function CopyStep({ state, what, onShow, onCopy, onCancel, problem, part }: {
  state: Copy; what: string; onShow: () => void; onCopy: () => void; onCancel: () => void; problem: string | null; part: string;
}) {
  const shown = state.phase !== 'editing';
  return (
    <>
      {shown ? <pre className="fb-preview" data-part={`${part}-preview`} aria-label={`Exactly what Copy ${what} writes`}>{state.bytes}</pre> : null}
      <div className="fb-step">
      <div className="fb-actions">
        {shown ? (
          <>
            <button type="button" className="btn primary" data-part={`${part}-copy`} aria-disabled={state.phase !== 'previewing' ? 'true' : undefined} onClick={onCopy}>Copy {what}</button>
            <button type="button" className="btn quiet" data-part={`${part}-cancel`} aria-disabled={state.phase === 'copying' ? 'true' : undefined} onClick={onCancel}>{state.phase === 'previewing' ? 'Cancel' : 'Edit'}</button>
          </>
        ) : (
          <button type="button" className="btn" data-part={`${part}-show`} aria-disabled={problem ? 'true' : undefined} onClick={onShow}>Preview {what}</button>
        )}
      </div>
      <p className="fb-said" role="status" aria-live="polite" data-part={`${part}-result`} data-phase={state.phase}>
        {state.phase === 'copied' ? <StatusGlyph tier="t2" /> : state.phase === 'not_copied' ? <StatusGlyph tier="t1" /> : null}
        {state.phase === 'copied' ? (part === 'handoff' ? 'Handoff copied. Nothing has been sent: paste it to your own agent.' : 'Copied. Nothing was shared or sent.')
          : state.phase === 'not_copied' ? 'Not copied: the browser refused the clipboard. Nothing was sent.'
            : !shown && problem ? problem : ''}
      </p>
      </div>
    </>
  );
}

export function FeedbackShare() {
  const [title, setTitle] = useState('');
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState('');
  const [message, setMessage] = useState('Have a look at OpenWiz.');
  const [handoff, handoffState] = useCopier();
  const [share, shareState] = useCopier();
  const feedbackIssue = feedbackProblem(title, body);
  const shareIssue = shareProblem(message);
  const locked = (s: Copy) => s.phase === 'copying';
  const onTitle = (v: string) => { if (!locked(handoffState)) { setTitle(v); handoff.cancel(); } };
  const onBody = (v: string) => { if (!locked(handoffState)) { setBody(v); handoff.cancel(); } };
  const onMessage = (v: string) => { if (!locked(shareState)) { setMessage(v); share.cancel(); } };
  const onShowHandoff = () => { if (!feedbackIssue) handoff.show(handoffText(title, body)); };
  const onShowShare = () => { if (!shareIssue) share.show(shareText(message)); };
  const onCopyHandoff = () => { void handoff.copy(); };
  const onCopyShare = () => { void share.copy(); };
  // Closed by default: Home stays one press away from the fields, and the words are kept while closed.
  if (!open) {
    return (
      <section className="feedback" data-part="feedback">
        <button type="button" className="btn fb-open" data-part="feedback-open" aria-expanded="false" onClick={() => setOpen(true)}>Feedback and sharing</button>
      </section>
    );
  }
  return (
    <section className="feedback" data-part="feedback" aria-labelledby="fb-heading">
      <div className="fb-head">
        <h2 id="fb-heading" className="fb-heading">Feedback and sharing</h2>
        <button type="button" className="btn quiet" data-part="feedback-close" aria-expanded="true" aria-disabled={locked(handoffState) || locked(shareState) ? 'true' : undefined} onClick={() => { if (!locked(handoffState) && !locked(shareState)) setOpen(false); }}>Close</button>
      </div>
      <div className="fb-card" data-part="handoff">
        <h3 className="fb-title">Send feedback through your own agent</h3>
        <p className="fb-note">Write only what you want anyone to read. Copying sends nothing: paste it to your own agent. It shows you the exact public issue for {DESTINATION} and creates it only after your yes, under your own GitHub login.</p>
        <label className="fb-field">
          <span>Title</span>
          <input type="text" data-part="handoff-title" value={title} aria-readonly={locked(handoffState) ? 'true' : undefined} onChange={(e) => onTitle(e.target.value)} />
        </label>
        <label className="fb-field">
          <span>Feedback</span>
          <textarea data-part="handoff-body" rows={5} value={body} aria-readonly={locked(handoffState) ? 'true' : undefined} onChange={(e) => onBody(e.target.value)} />
        </label>
        <CopyStep state={handoffState} what="handoff" part="handoff" problem={feedbackIssue} onShow={onShowHandoff} onCopy={onCopyHandoff} onCancel={() => handoff.cancel()} />
        <ol className="fb-stages" data-part="feedback-stages" aria-label="What each step means">
          <li><strong>Copied</strong>: here, on your device. Nothing has left it.</li>
          <li><strong>Sent</strong>: only by your agent, after you say yes to its exact preview.</li>
          <li><strong>Acknowledged</strong>: only when Jake replies on that issue.</li>
        </ol>
      </div>
      <div className="fb-card" data-part="share">
        <h3 className="fb-title">Share OpenWiz</h3>
        <p className="fb-note">Copies your message and the public OpenWiz link. Nothing is posted or sent, and no access is given.</p>
        <label className="fb-field">
          <span>Message</span>
          <input type="text" data-part="share-text" value={message} aria-readonly={locked(shareState) ? 'true' : undefined} onChange={(e) => onMessage(e.target.value)} />
        </label>
        <CopyStep state={shareState} what="share" part="share" problem={shareIssue} onShow={onShowShare} onCopy={onCopyShare} onCancel={() => share.cancel()} />
      </div>
    </section>
  );
}
