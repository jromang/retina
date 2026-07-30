// Perspective names are domain identifiers (keys of the JSON files on the server side,
// arguments to `app.layout.load('Processing')`): they are not translated. What the interface
// displays goes through `perspectiveLabel` — and every built-in perspective must have its
// mapping there, otherwise the raw id would show up untranslated.

import { describe, expect, it } from 'vitest';

import { m } from '../src/paraglide/messages';
import { BUILTIN_PERSPECTIVES, perspectiveLabel } from '../src/shell/panels';

describe('perspectiveLabel', () => {
  it('covers every built-in perspective with a message from the catalogue', () => {
    const expected: Record<string, string> = {
      Processing: m.perspective_processing(),
      Inspection: m.perspective_inspection(),
      Script: m.perspective_script(),
    };
    for (const name of BUILTIN_PERSPECTIVES) {
      expect(Object.keys(expected), `built-in perspective without a label: ${name}`).toContain(name);
      expect(perspectiveLabel(name)).toBe(expected[name]);
    }
  });

  it('passes a user perspective name through as is', () => {
    expect(perspectiveLabel('My M31 evening')).toBe('My M31 evening');
  });
});
