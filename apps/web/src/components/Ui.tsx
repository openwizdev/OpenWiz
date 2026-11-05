import type { ButtonHTMLAttributes, HTMLAttributes } from 'react';

export function Button({ variant = 'secondary', className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'quiet' }) {
  return <button type="button" className={`btn ${variant} ${className}`} {...props} />;
}
export function SectionLabel(props: HTMLAttributes<HTMLHeadingElement>) {
  return <h2 {...props} className={`kicker ${props.className ?? ''}`} />;
}
export function SoftPanel(props: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={`soft-panel ${props.className ?? ''}`} />;
}
