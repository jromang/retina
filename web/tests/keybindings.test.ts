// The keybinding table — and above all its invariant: one chord, one command.
//
// Two failure modes this file locks down:
//
//   1. **the duplicate** — two commands both claiming `Ctrl+B`. Without a test, the winner
//      depends on the registry's declaration order, and the shortcut changes meaning the day
//      someone reorders an array. This test is what found `panel.windows`/`zone.sidebar` and
//      `panel.console`/`zone.bottom`, which were fighting over Ctrl+B and Ctrl+J;
//   2. **the decorative shortcut** — a `shortcut` the palette displays and nothing wires up.
//      That was the starting state of the `+`, `−`, `1` and `F` keys.

import { describe, expect, it, vi } from 'vitest';

import type { ProcessMeta } from '../src/api/types';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const { buildKeymap, chordKey, eventChord, firesWhileTyping, parseChord } = await import(
  '../src/shell/keybindings'
);
const { baseCommands, commandIndex } = await import('../src/shell/commands');

function key(init: Partial<KeyboardEvent> & { key: string }): KeyboardEvent {
  return {
    key: init.key,
    ctrlKey: init.ctrlKey ?? false,
    altKey: init.altKey ?? false,
    shiftKey: init.shiftKey ?? false,
    metaKey: init.metaKey ?? false,
  } as KeyboardEvent;
}

const CATALOG: ProcessMeta[] = [];

describe('parsing a chord', () => {
  it('recognizes the usual combinations', () => {
    expect(parseChord('Ctrl+Shift+P')).toEqual({ ctrl: true, alt: false, shift: true, key: 'p' });
    expect(parseChord('F5')).toEqual({ ctrl: false, alt: false, shift: false, key: 'f5' });
    expect(parseChord('Ctrl+Alt+1')).toEqual({ ctrl: true, alt: true, shift: false, key: '1' });
  });

  it('treats `+` as a key, not as a separator', () => {
    // `'+'.split('+')` yields two empty strings: without a special case, zoom-in would have no
    // shortcut at all and nobody would have noticed.
    expect(parseChord('+')).toEqual({ ctrl: false, alt: false, shift: false, key: '+' });
    expect(parseChord('Ctrl++')).toEqual({ ctrl: true, alt: false, shift: false, key: '+' });
  });

  it('maps the typographic minus sign back onto the keyboard one', () => {
    // The palette displays U+2212 (−); `KeyboardEvent.key` yields a plain hyphen.
    expect(parseChord('−')?.key).toBe('-');
    expect(chordKey(parseChord('−')!)).toBe(eventChord(key({ key: '-' })));
  });

  it('rejects an unknown modifier rather than ignoring it', () => {
    expect(parseChord('Hyper+K')).toBeNull();
  });
});

describe('matching against the event', () => {
  it('requires modifiers to match exactly', () => {
    // The trap in the old cascade of `if`s: `event.ctrlKey && key === 'b'` is true for
    // Ctrl+Alt+B, which therefore toggled the wrong zone whenever the order changed.
    expect(eventChord(key({ key: 'b', ctrlKey: true }))).toBe('ctrl+b');
    expect(eventChord(key({ key: 'b', ctrlKey: true, altKey: true }))).toBe('ctrl+alt+b');
    expect(eventChord(key({ key: 'b', ctrlKey: true }))).not.toBe(
      eventChord(key({ key: 'b', ctrlKey: true, altKey: true })),
    );
  });

  it('ignores a modifier pressed on its own', () => {
    expect(eventChord(key({ key: 'Control', ctrlKey: true }))).toBeNull();
  });

  it('lets only the escape hatches through while the user is typing', () => {
    expect(firesWhileTyping('ctrl+shift+p')).toBe(true);
    expect(firesWhileTyping('f1')).toBe(true);
    // A bare key while typing: you are writing a `+`, not zooming in.
    expect(firesWhileTyping('+')).toBe(false);
    // Ctrl+B means "bold" in plenty of fields: we do not hijack that one either.
    expect(firesWhileTyping('ctrl+b')).toBe(false);
  });
});

describe('table derived from the registry', () => {
  const commands = baseCommands([]);
  const keymap = buildKeymap(commands);

  it('never assigns two commands to the same shortcut', () => {
    // `buildKeymap` throws on a duplicate: the assertion is therefore that it does not.
    expect(() => buildKeymap(commands)).not.toThrow();
  });

  it('wires up every non-contextual `shortcut` in the registry', () => {
    const expected = commands.filter((command) => command.shortcut && !command.localShortcut);
    expect(expected.length).toBeGreaterThan(10);
    for (const command of expected) {
      const chord = parseChord(command.shortcut!);
      expect(chord, `unreadable shortcut: ${command.shortcut} (${command.id})`).not.toBeNull();
      expect(keymap.get(chordKey(chord!))).toBe(command.id);
    }
  });

  it('resolves every entry to an existing command', () => {
    const index = commandIndex([], CATALOG);
    for (const id of keymap.values()) {
      expect(index.has(id), `${id} is not in the registry`).toBe(true);
    }
  });

  it('wires up the viewport keys, which had no handler at all', () => {
    expect(keymap.get('+')).toBe('view.zoom_in');
    expect(keymap.get('-')).toBe('view.zoom_out');
    expect(keymap.get('1')).toBe('view.zoom_11');
    expect(keymap.get('f')).toBe('view.zoom_fit');
    expect(keymap.get('b')).toBe('view.compare_ab');
  });

  it('leaves contextual shortcuts to their own component', () => {
    // Monaco binds Ctrl+S and F5 inside the editor; globally these chords belong to
    // "save the image" and "apply the last process".
    expect(keymap.get('ctrl+s')).toBe('file.save_as');
    expect(keymap.get('f5')).toBe('process.apply_last');
  });

  it('gives the zones their toggles, and the palette its own', () => {
    expect(keymap.get('ctrl+b')).toBe('zone.sidebar');
    expect(keymap.get('ctrl+j')).toBe('zone.bottom');
    expect(keymap.get('ctrl+alt+b')).toBe('zone.right');
    expect(keymap.get('ctrl+shift+p')).toBe('palette.open');
  });
});
