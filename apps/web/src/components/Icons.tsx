import type { ReactNode } from 'react';
function Icon({ children }: { children: ReactNode }) {
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}
export function HomeIcon() { return <Icon><path d="m3 10 9-7 9 7M5 9v12h5v-7h4v7h5V9" /></Icon>; }
export function SessionsIcon() { return <Icon><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5M3 16l9 5 9-5" /></Icon>; }
export function FleetsIcon() { return <Icon><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></Icon>; }
export function PlusIcon() { return <Icon><path d="M12 5v14M5 12h14" /></Icon>; }
export function CloseIcon() { return <Icon><path d="m6 6 12 12M18 6 6 18" /></Icon>; }
export function BackIcon() { return <Icon><path d="m14 5-7 7 7 7" /></Icon>; }
export function FileIcon() { return <Icon><path d="M14 3H6v18h13V8l-5-5Z" /><path d="M14 3v5h5M8 13h8M8 17h5" /></Icon>; }
export function AttachIcon() { return <Icon><path d="m8 12 7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7l9-9M6 14l9-9" /></Icon>; }
export function ChevronIcon({ open = false }: { open?: boolean }) { return <svg className={`icon chevron${open ? ' open' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m7 10 5 5 5-5" /></svg>; }

export function SearchIcon() { return <Icon><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></Icon>; }
