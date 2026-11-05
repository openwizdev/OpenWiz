// #2292: the app's half of contracts/feedback.v1.md. The owner writes only the
// public feedback they choose, and copies a handoff of it for their own agent
// (which previews it and asks for a yes before creating anything); or
// previews and copies a share of the one allowlisted public URL. Nothing here
// sends, stores, reads or collects anything: the only effect is one clipboard
// write of exactly the previewed text, after an explicit copy.

export const DESTINATION = 'openwizdev/openwiz';
export const SHARE_URL = 'https://github.com/openwizdev/openwiz';
export const TITLE_MAX = 256;
// GitHub's 65,536-character body, less the blank line and the 59-character
// marker line the agent adds (contracts/feedback.v1.md, "The issue").
export const BODY_MAX = 65536 - 61;

export type Clipboard = { writeText(text: string): Promise<void> };

/** One copy affordance: copied only after the clipboard write succeeds. */
export type Copy =
  | { phase: 'editing' }
  | { phase: 'previewing'; bytes: string }
  | { phase: 'copying'; bytes: string }
  | { phase: 'copied'; bytes: string }
  | { phase: 'not_copied'; bytes: string };

const title = (t: string) => t.trim();
const body = (b: string) => b.replace(/\r\n/g, '\n').trimEnd();

/** Why this feedback can't be handed off yet, or null. Never trimmed to fit. */
export function feedbackProblem(t: string, b: string): string | null {
  if (!title(t) || /[\r\n]/.test(title(t))) return 'Write a one-line title.';
  if (title(t).length > TITLE_MAX) return `Shorten the title to ${TITLE_MAX} characters.`;
  if (!body(b).trim()) return 'Write what you want Jake to read.';
  if (body(b).length > BODY_MAX) return 'Shorten the feedback; it is longer than GitHub allows.';
  if (/\r/.test(body(b)) || body(b).split('\n').some((line) => line.startsWith('OpenWiz feedback operation '))) return 'Remove the feedback marker line; your agent adds it.';
  return null;
}

/** The exact handoff for the owner's own agent: a fixed instruction and the chosen words, nothing else. */
export function handoffText(t: string, b: string): string {
  return [
    'Please send this as public feedback about OpenWiz with the OpenWiz feedback skill (openwiz:feedback).',
    `It becomes one public issue on ${DESTINATION}, under my own GitHub login.`,
    'Show me the exact preview first, and create nothing until I say yes.',
    '',
    `Title: ${title(t)}`,
    '',
    'Body:',
    body(b),
  ].join('\n');
}

const URLISH = /[a-z][a-z0-9+.-]*:\/\/|\bwww\.|\blocalhost\b|\b\d{1,3}(\.\d{1,3}){3}\b/i;

/** Why this share text can't be previewed, or null: no link, address or local host of its own. */
export function shareProblem(text: string): string | null {
  const t = text.replace(/\r\n/g, '\n').trim();
  if (!t) return 'Write a short message.';
  if (URLISH.test(t) || /\r/.test(t)) return 'Leave out links and addresses; the OpenWiz link is added on its own.';
  return null;
}

/** The exact share: the owner's text, a blank line, and the one allowlisted URL. */
export function shareText(text: string): string {
  return `${text.replace(/\r\n/g, '\n').trim()}\n\n${SHARE_URL}`;
}

/** One preview-then-copy affordance. The clipboard is written once, only by `copy`, only with the previewed bytes. */
export class Copier {
  private state: Copy = { phase: 'editing' };
  private readonly listeners = new Set<() => void>();

  private readonly clipboard: Clipboard | null;

  constructor(clipboard: Clipboard | null) {
    this.clipboard = clipboard;
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  snapshot = (): Copy => this.state;

  private set(next: Copy) {
    this.state = next;
    for (const l of this.listeners) l();
  }

  /** Shows exactly these bytes as what a copy will write. */
  show(bytes: string) {
    if (this.state.phase !== 'copying') this.set({ phase: 'previewing', bytes });
  }

  /** Back to editing: a cancel, or any change to the words. Touches nothing. */
  cancel() {
    if (this.state.phase !== 'editing' && this.state.phase !== 'copying') this.set({ phase: 'editing' });
  }

  /** The one clipboard write, of the previewed bytes; a repeat or a copy without a preview writes nothing. */
  async copy(): Promise<void> {
    if (this.state.phase !== 'previewing') return;
    const bytes = this.state.bytes;
    this.set({ phase: 'copying', bytes });
    try {
      if (!this.clipboard) throw new Error('no clipboard');
      await this.clipboard.writeText(bytes);
      this.set({ phase: 'copied', bytes });
    } catch {
      this.set({ phase: 'not_copied', bytes });
    }
  }
}
