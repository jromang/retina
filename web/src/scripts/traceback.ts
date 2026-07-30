// Reading an IPython traceback to bring the cursor back to the offending line.
//
// The reference implementation prints `…, line N` in its console and stops there: nothing links
// that text to its editor. This is a place where getting ahead costs one regular expression —
// provided the two pitfalls below are handled.
//
// **The deepest frame is the last one.** A traceback crosses several frames, and several of
// them can come from IPython cells (a function defined in an earlier cell, called from this
// one). It is the *last* occurrence that designates where the exception was raised; taking the
// first would point at the caller.
//
// **A selection shifts everything.** "Run selection" sends a fragment: its line 1 is line L of
// the editor. Without the offset, the marker invariably lands at the top of the file — the most
// confusing error possible, because it is plausible.

/** `Cell In[12], line 34` — the IPython 8/9 format, with or without indentation. */
const CELL_LINE = /Cell In\[\d+\],\s*line\s+(\d+)/g;

export interface TracebackLocation {
  /** 1-based line **within the executed fragment**, not yet within the editor. */
  line: number;
}

export function parseTraceback(text: string): TracebackLocation | null {
  let last: number | null = null;
  for (const match of text.matchAll(CELL_LINE)) {
    const line = Number(match[1]);
    if (Number.isFinite(line) && line > 0) last = line;
  }
  return last === null ? null : { line: last };
}

/** Maps a line of the executed fragment back to its line in the editor. */
export function editorLine(location: TracebackLocation, lineOffset: number): number {
  return location.line + lineOffset;
}
