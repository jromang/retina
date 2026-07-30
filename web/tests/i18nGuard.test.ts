// Guard rail: no interface string may stay hardcoded in a component.
//
// Same spirit as `menus.test.ts` — an architectural invariant entrusted to a test rather than to
// review, with assertions on **empty lists** whose message names every offender.
//
// # What this test catches, and that `tsc` cannot see
//
// Paraglide already does half the work: a key missing from the catalogue is a compile error. What
// it cannot see is the string nobody thought to extract — a `title="Save"` dashed off in a new
// panel compiles perfectly and will never appear in French. That is how an i18n fails: it does not
// break, it degrades, panel by panel.
//
// # Two probes, and why these two
//
// 1. **an accent inside a literal** — a near-perfect signal after the migration: French has left
//    the code, so any reappearance is a forgotten string;
// 2. **a UI attribute (`title`, `aria-label`, `placeholder`…) assigned a multi-word literal** —
//    catches what the first one misses: a string written straight in English, which would never
//    be translated into French.
//
// # What is deliberately out of scope
//
// Messages aimed at the **developer** — `console.*`, internal `throw new Error(...)` — are exempt:
// they never reach the screen, and translating them would cost without buying anything. The
// filtering is done line by line rather than by parsing: crude, but a line holding both a
// `console.error` and an interface string is a readability problem before it is an i18n one.

import { describe, expect, it } from 'vitest';

/**
 * The sources, read by Vite rather than by `node:fs`.
 *
 * `@types/node` would have done the job, but adding it to the tsconfig's `types` redefines
 * `setTimeout` as `NodeJS.Timeout` **for the whole project**: four shell files stopped compiling.
 * `import.meta.glob` is the bundler mechanism that already carries this test anyway, and it has no
 * side effect on global typing.
 *
 * Paraglide-generated code is excluded from the pattern: those files are the catalogues themselves.
 */
const SOURCES = import.meta.glob('../src/**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

/**
 * Justified exceptions, per file. The value is a fragment of the offending line.
 *
 * Every entry must carry its reason. An allowlist that grows without comment is the symptom of a
 * guard rail nobody believes in any more — which is why this one is empty, and stays empty until
 * a case genuinely needs it. The entries it used to hold are all covered elsewhere now: the
 * hardcoded strings in `shell/commands.ts` were translated, the keymap collision in
 * `shell/keybindings.ts` is a `throw new Error(...)` and therefore exempt by rule, and the French
 * key aliases beside it are object *keys* rather than literals, which the accent probe never saw.
 */
const ALLOWED: Array<{ file: string; fragment: string; why: string }> = [];

/** Attributes whose value lands on screen. */
const UI_ATTRIBUTES = /\b(title|aria-label|placeholder|alt|confirmLabel)\s*=\s*(['"])([^'"]{4,})\2/g;

const ACCENTED = /[éèêëàâäùûüôöîïçœÉÈÊËÀÂÄÙÛÜÔÖÎÏÇŒ]/;

/** A literal, whatever its delimiter — template strings included. */
const LITERAL = /(['"`])((?:(?!\1)[^\\]|\\.)*)\1/g;

interface Offence {
  file: string;
  line: number;
  text: string;
}

/** Paths relative to `src/`, in a stable order — the failure report has to be readable. */
function sources(): string[] {
  return Object.keys(SOURCES)
    .map((path) => path.replace('../src/', ''))
    .filter((path) => !path.startsWith('paraglide/'))
    .sort();
}

/**
 * Strips comments from a file while preserving line numbering.
 *
 * Done line by line but **with state**: a block comment — above all a JSX `{/* … *​/}`, which often
 * runs over five lines — is only recognisable by remembering the previous line. The first version
 * tested `trimmed.startsWith('*')`, and therefore mistook the *inner* lines of a French comment for
 * code: four false positives, all of them prose. A French apostrophe opens a spurious literal on
 * top of that, which made the report unreadable.
 */
function stripComments(source: string): string[] {
  let inBlock = false;
  return source.split('\n').map((line) => {
    let out = '';
    let index = 0;
    while (index < line.length) {
      if (inBlock) {
        const end = line.indexOf('*/', index);
        if (end < 0) return out;
        inBlock = false;
        index = end + 2;
        continue;
      }
      const block = line.indexOf('/*', index);
      const inline = line.indexOf('//', index);
      if (inline >= 0 && (block < 0 || inline < block)) {
        return out + line.slice(index, inline);
      }
      if (block >= 0) {
        out += line.slice(index, block);
        inBlock = true;
        index = block + 2;
        continue;
      }
      return out + line.slice(index);
    }
    return out;
  });
}

/** True for lines that do not address the user. */
function isExempt(line: string): boolean {
  return (
    // Developer messages: never in the DOM.
    line.includes('console.') ||
    line.includes('throw new Error(') ||
    // Python echo: code, not interface.
    /\bpython:\s/.test(line)
  );
}

function allowed(file: string, line: string): boolean {
  return ALLOWED.some((rule) => file.endsWith(rule.file) && line.includes(rule.fragment));
}

function scan(check: (file: string, line: string) => string | null): Offence[] {
  const offences: Offence[] = [];
  for (const file of sources()) {
    const content = stripComments(SOURCES[`../src/${file}`] ?? '');
    content.forEach((line, index) => {
      if (isExempt(line) || allowed(file, line)) return;
      const text = check(file, line);
      if (text !== null) offences.push({ file, line: index + 1, text });
    });
  }
  return offences;
}

function report(offences: Offence[]): string {
  return offences.map((o) => `${o.file}:${o.line}  ${o.text.trim().slice(0, 100)}`).join('\n  ');
}

describe('i18n guard rail', () => {
  it('leaves no French text in the sources', () => {
    const offences = scan((_file, line) => {
      LITERAL.lastIndex = 0;
      for (const match of line.matchAll(LITERAL)) {
        if (ACCENTED.test(match[2] ?? '')) return line;
      }
      return null;
    });

    expect(offences, `French strings outside the catalogue:\n  ${report(offences)}`).toEqual([]);
  });

  it('leaves no UI attribute on a hardcoded literal', () => {
    const offences = scan((_file, line) => {
      UI_ATTRIBUTES.lastIndex = 0;
      for (const match of line.matchAll(UI_ATTRIBUTES)) {
        const value = match[3] ?? '';
        // A single word is nearly always an identifier, a class or a unit; the probe aims at the
        // *sentence*, which is never anything but interface text.
        if (value.includes(' ')) return line;
      }
      return null;
    });

    expect(offences, `hardcoded UI attributes:\n  ${report(offences)}`).toEqual([]);
  });

  it('actually covers the sources — otherwise it would pass green without reading anything', () => {
    // A guard rail that finds no file is green and useless. That has happened often enough to
    // deserve its own assertion.
    expect(sources().length).toBeGreaterThan(50);
  });
});
