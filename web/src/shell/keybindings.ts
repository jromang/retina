// Shortcut table — derived from the command registry, not parallel to it.
//
// # The defect this module fixes
//
// `Command.shortcut` was purely decorative: the palette displayed it, and a `keydown` hard-coded
// in the workbench reimplemented *some* of those actions — sometimes differently (the
// handler's Ctrl+Z called `app.undo` directly, duplicating the `edit.undo` command). The
// viewport keys advertised in the palette (`+`, `−`, `1`, `F`) had no
// handler at all: the palette advertised shortcuts that did not exist.
//
// The keymap is therefore **built** from `commandIndex()`: a `shortcut` laid on a
// command is wired by construction, and the tooltip that displays it can no longer lie.
//
// # Two rules that avoid the classic failures
//
// **Exact modifiers.** `Ctrl+Alt+B` and `Ctrl+B` are two distinct chords; a cascade
// of `if`s testing `event.ctrlKey && key === 'b'` fires the second on the first, hence
// the carefully chosen order of the old handler. Here the equality is exact, the order no longer
// matters.
//
// **One chord, one command.** Duplicates throw at build time: two commands on the
// same shortcut is an arbitration that must be made while writing the code, not at the mercy of
// insertion order. The *contextual* shortcuts (Ctrl+S and F5 in the script editor,
// laid down by Monaco) are marked `localShortcut` and excluded from the table — without which they
// would collide with "save the image" and "apply the last process".

import { m } from '../paraglide/messages';
import type { Command } from './commands';

export interface Chord {
  ctrl: boolean;
  alt: boolean;
  shift: boolean;
  /** Normalized key, lowercase for letters. */
  key: string;
}

/** Chords allowed even inside an input field. */
const WHILE_TYPING = new Set(['ctrl+shift+p', 'f1']);

/**
 * Display synonyms → `KeyboardEvent.key`.
 *
 * The vocabulary of `Command.shortcut` is **canonical and untranslated**: `Esc`, `Enter`,
 * `Space`, `Del`. Localizing the source string would force this parser to know every
 * language — a shortcut would stop working because the language was changed, which is
 * exactly the kind of failure one never traces back to its cause. Translation happens at
 * **display** time (`shortcutParts`), not here. The French forms remain accepted: they
 * cost nothing and keep a forgotten French spelling in a `shortcut:` from failing silently.
 */
const ALIASES: Record<string, string> = {
  '−': '-', // U+2212, used for display: the event itself sends an ordinary hyphen
  esc: 'escape',
  del: 'delete',
  space: ' ',
  entrée: 'enter',
  échap: 'escape',
  espace: ' ',
  suppr: 'delete',
};

/** Displayable name of a canonical key — this is where, and only where, we translate. */
function keyLabel(part: string): string {
  switch (part) {
    case 'ctrl':
      return m.key_ctrl();
    case 'alt':
      return m.key_alt();
    case 'shift':
      return m.key_shift();
    case 'escape':
      return m.key_esc();
    case 'enter':
      return m.key_enter();
    case ' ':
      return m.key_space();
    case 'delete':
      return m.key_delete();
    default:
      return part.toUpperCase();
  }
}

/**
 * A canonical chord (`ctrl+shift+p`) as displayable keys, in the order they are pressed.
 *
 * Shared by the cheat sheet, the palette and the menus — without which the three would display
 * three notations, and only one would be translated.
 */
export function shortcutParts(chord: string): string[] {
  // No `split('+')`: the key *is* sometimes `+` (zoom in), and a naive split returned
  // two empty labels. Since the canonical form is `[ctrl+][alt+][shift+]<key>`, we strip the
  // modifiers from the head and what remains is the key, whatever it is.
  const parts: string[] = [];
  let rest = chord;
  for (const modifier of ['ctrl', 'alt', 'shift']) {
    if (rest.startsWith(`${modifier}+`)) {
      parts.push(keyLabel(modifier));
      rest = rest.slice(modifier.length + 1);
    }
  }
  parts.push(keyLabel(rest));
  return parts;
}

/** The same, flattened — what the palette and the menus expect, since they display one string. */
export function formatShortcut(shortcut: string): string {
  const chord = parseChord(shortcut);
  return chord ? shortcutParts(chordKey(chord)).join('+') : shortcut;
}

export function parseChord(shortcut: string): Chord | null {
  const text = shortcut.trim();
  if (!text) return null;
  // `'+'.split('+')` returns two empty strings: in "zoom in", the `+` is the **key**,
  // not a separator. Same thing at the end of a chord (`Ctrl++`).
  const parts = text.split('+').map((part) => part.trim());
  const last = parts.pop();
  const raw = last === '' && text.endsWith('+') ? '+' : last;
  if (!raw) return null;
  if (raw === '+' && parts.at(-1) === '') parts.pop();
  const key = normalizeKey(raw);
  const modifiers = parts.map((part) => part.toLowerCase());
  const known = ['ctrl', 'alt', 'shift', 'cmd', 'meta'];
  if (modifiers.some((modifier) => !known.includes(modifier))) return null;
  return {
    ctrl: modifiers.includes('ctrl') || modifiers.includes('cmd') || modifiers.includes('meta'),
    alt: modifiers.includes('alt'),
    shift: modifiers.includes('shift'),
    key,
  };
}

function normalizeKey(raw: string): string {
  const lower = raw.toLowerCase();
  return ALIASES[lower] ?? lower;
}

/** Canonical form of a chord — the keymap's key. */
export function chordKey(chord: Chord): string {
  return `${chord.ctrl ? 'ctrl+' : ''}${chord.alt ? 'alt+' : ''}${chord.shift ? 'shift+' : ''}${chord.key}`;
}

/** The chord pressed, in the same form. `null` if the event carries only a modifier. */
export function eventChord(event: KeyboardEvent): string | null {
  if (['Control', 'Alt', 'Shift', 'Meta'].includes(event.key)) return null;
  return chordKey({
    ctrl: event.ctrlKey || event.metaKey,
    alt: event.altKey,
    shift: event.shiftKey,
    key: normalizeKey(event.key),
  });
}

/**
 * Builds `chord → command id`.
 *
 * Throws on a duplicate: that is a programming error, and letting it through would give a
 * shortcut whose meaning depends on the registry's declaration order.
 */
export function buildKeymap(commands: Iterable<Command>): Map<string, string> {
  const keymap = new Map<string, string>();
  for (const command of commands) {
    if (!command.shortcut || command.localShortcut) continue;
    const chord = parseChord(command.shortcut);
    if (!chord) continue;
    const key = chordKey(chord);
    const existing = keymap.get(key);
    if (existing && existing !== command.id) {
      throw new Error(`raccourci ${command.shortcut} revendiqué par ${existing} et ${command.id}`);
    }
    keymap.set(key, command.id);
  }
  return keymap;
}

/**
 * Must the chord fire while the focus is in an input?
 *
 * The bare keys (`+`, `1`, `F`) obviously must not — one is typing.
 * But neither must the chords with modifiers, by default: Ctrl+B is "bold" in many
 * fields. Only the interface's escape hatches are exceptions.
 */
export function firesWhileTyping(chord: string): boolean {
  return WHILE_TYPING.has(chord);
}

/**
 * Is the event's target an input?
 *
 * `closest('.monaco-editor')` and not only the textarea: Monaco puts the focus on a
 * hidden textarea, but the click that gives it focus first passes through the editor's root. A
 * character typed in that interval saw the guard let it through, and the corresponding bare
 * shortcut swallowed it — the first character of a fast keystroke disappeared.
 */
export function isTyping(target: EventTarget | null): boolean {
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return true;
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || target.closest('.monaco-editor') !== null;
}
