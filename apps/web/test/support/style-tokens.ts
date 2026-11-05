// Test-only reader for the app's base colour tokens and compatibility aliases.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

export const css = readFileSync(new URL('../../styles/globals.css', import.meta.url), 'utf8');
const tokensCss = readFileSync(new URL('../../styles/tokens.css', import.meta.url), 'utf8');
// Read the base roots in stylesheet order; aliases can point through either file.
const root = [tokensCss, css].map((sheet) => {
  const match = /:root\s*\{([^}]*)\}/.exec(sheet.replace(/\/\*[\s\S]*?\*\//g, ''));
  assert.ok(match?.[1], 'stylesheet :root');
  return match[1];
}).join('\n');
const values = new Map([...root.matchAll(/--([a-z0-9-]+)\s*:\s*([^;]+);/g)]
  .map((m) => [m[1] ?? '', (m[2] ?? '').trim()]));
export const token = (name: string): string => {
  const seen = new Set<string>();
  let current = name;
  for (;;) {
    assert.ok(!seen.has(current), `cyclic token --${current}`);
    seen.add(current);
    const value = values.get(current);
    assert.ok(value, `token --${current}`);
    if (/^#[0-9a-f]{6}$/i.test(value)) return value;
    const alias = /^var\(--([a-z0-9-]+)\)$/.exec(value);
    assert.ok(alias?.[1], `token --${current} must be a hex colour or alias`);
    current = alias[1];
  }
};
