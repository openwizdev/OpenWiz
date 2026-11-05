// The fleets list (#125) in a page like the app's, for the browser proofs and
// the renders: its markup inside `<main>`, with the app's own stylesheet,
// fonts and Content Security Policy. Test only.
//
// Fleets.tsx is JSX, which Node's type stripping can't read: the TypeScript
// compiler turns it into JavaScript as it loads.

import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { fileURLToPath } from 'node:url';

import type { Browser, Page } from 'playwright-core';
import { createElement, isValidElement } from 'react';
import type { ReactNode } from 'react';
import ts from 'typescript';

import type { FleetsProps } from '../../src/components/Fleets.tsx';

registerHooks({
  load(url, context, nextLoad) {
    if (!url.startsWith('file:') || !url.endsWith('.tsx')) return nextLoad(url, context);
    const file = fileURLToPath(url);
    const compilerOptions = { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: true };
    return { format: 'module', source: ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions }).outputText, shortCircuit: true };
  },
});
const fleetsModule: typeof import('../../src/components/Fleets.tsx') = await import('../../src/components/Fleets.tsx');
const { renderToStaticMarkup } = await import('react-dom/server');
const { PAGE_CSP }: { PAGE_CSP: string } = await import(String(new URL('./serve.mjs', import.meta.url)));

export const { Fleets } = fleetsModule;
export const PHONE = { width: 390, height: 844 };
export const DESKTOP = { width: 1440, height: 900 };

const WEB = new URL('../../', import.meta.url);
const ORIGIN = 'http://fleets.test';
const html = (body: string) =>
  `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>DEMO</title><link rel="stylesheet" href="/globals.css"></head><body><main>${body}</main></body></html>`;

export const markupOf = (props: FleetsProps): string => renderToStaticMarkup(createElement(Fleets, props));

export type FleetsPage = { page: Page; markup: string; csp: () => Promise<unknown>; close: () => Promise<void> };

/** A fresh page at `viewport` showing `<Fleets {...props}>`, its fonts loaded. */
export async function fleetsPage(browser: Browser, viewport: { width: number; height: number }, props: FleetsProps): Promise<FleetsPage> {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1, reducedMotion: 'reduce', timezoneId: 'UTC', locale: 'en-GB' });
  const page = await context.newPage();
  const markup = markupOf(props);
  await page.route(`${ORIGIN}/**`, (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/') return route.fulfill({ status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': PAGE_CSP }, body: html(markup) });
    if (path === '/tokens.css') return route.fulfill({ status: 200, contentType: 'text/css', body: readFileSync(new URL('styles/tokens.css', WEB)) });
    if (path === '/globals.css') return route.fulfill({ status: 200, contentType: 'text/css', body: readFileSync(new URL('styles/globals.css', WEB)) });
    if (/^\/fonts\/[A-Za-z-]+\.woff2$/.test(path)) return route.fulfill({ status: 200, contentType: 'font/woff2', body: readFileSync(new URL(`public${path}`, WEB)) });
    return route.fulfill({ status: 404, body: '' });
  });
  await page.addInitScript({ content: "window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));" });
  await page.goto(`${ORIGIN}/`);
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  return { page, markup, csp: () => page.evaluate('window.__csp'), close: () => context.close() };
}

/** Every element a component renders, its own components called through (they keep no state). */
export function elements(node: ReactNode): { type: unknown; props: Record<string, unknown> }[] {
  if (Array.isArray(node)) return node.flatMap((n: ReactNode) => elements(n));
  if (!isValidElement<Record<string, unknown>>(node)) return [];
  if (typeof node.type === 'function') return elements(Reflect.apply(node.type, undefined, [node.props]));
  return [{ type: node.type, props: node.props }, ...elements(node.props['children'] as ReactNode)];
}
