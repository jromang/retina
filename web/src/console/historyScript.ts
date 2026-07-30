// "New script from history" — the transcript, turned into a file.
//
// # Why this is nearly free, and yet a differentiator
//
// The transcript contains two kinds of *executable* Python: what the user typed (`input`
// blocks) and the echo of the interface gestures (`echo` blocks, produced by
// `Application._echo` for every action). Both arrive in chronological order. There is
// therefore nothing to reconstruct: concatenation is enough, and the click → script → batch
// processing path opens up.
//
// # What has to be neutralized
//
// IPython magics (`%timeit`), shell commands (`!ls`) and the help `?` are valid in the console
// but not in a file handed to `app.run_recipe`, which does a plain `exec`. Comment them out
// rather than dropping them: the user sees what was set aside, and can decide.

import type { Block } from './transcript';

const MAGIC = /^\s*[%!]/;
const HELP = /\?\s*$/;

/** True if the line would not execute outside the IPython console. */
function isConsoleOnly(line: string): boolean {
  return MAGIC.test(line) || (HELP.test(line) && line.trim().length > 1);
}

function neutralize(code: string): string {
  return code
    .split('\n')
    // A comment **of the generated script**: this is Python code, not interface text — it stays
    // in English whatever the shell's language.
    .map((line) => (isConsoleOnly(line) ? `# (console only) ${line.trim()}` : line))
    .join('\n');
}

/**
 * Assembles a script from the transcript blocks.
 *
 * `stamp` is passed in rather than read from the clock: a pure function can be tested, and the
 * caller knows better what to display.
 */
export function scriptFromBlocks(blocks: readonly Block[], stamp: string): string {
  const lines = blocks
    .filter((block) => block.kind === 'input' || block.kind === 'echo')
    .map((block) => neutralize(block.text.replace(/\s+$/, '')))
    .filter((text) => text.trim().length > 0);

  // Header **of the generated script**: hard-coded English, for the same reason as above.
  const header = [
    '# Script generated from a Retina session.',
    `# ${stamp} — ${lines.length} statement(s): what was typed in the console and`,
    '# the echo of the interface gestures, in the order they happened.',
    '',
  ];
  return [...header, ...lines, ''].join('\n');
}
