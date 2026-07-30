// Reading an IPython traceback — the part that decides where the marker lands.
//
// Both failure modes are silent: a marker placed on the wrong line is *plausible*, so nobody
// reports it. Hence the insistence on the deepest frame and on the offset of a selection.

import { describe, expect, it } from 'vitest';

import { editorLine, parseTraceback } from '../src/scripts/traceback';

/** A real IPython 9 traceback for `a = 1 / 0` on the third line (captured on the server). */
const SIMPLE = `---------------------------------------------------------------------------
ZeroDivisionError                         Traceback (most recent call last)
Cell In[1], line 3
      1 a = 1
      2 b = 2
----> 3 c = a / 0
      4 d = 4

ZeroDivisionError: division by zero`;

const SYNTAX = `  Cell In[2], line 1
    def f(:
          ^
SyntaxError: invalid syntax`;

/** A function defined in an earlier cell, called from this one. */
const NESTED = `Cell In[7], line 2
      1 x = 1
----> 2 boom()

Cell In[6], line 5, in boom()
      4 def boom():
----> 5     return 1 / 0

ZeroDivisionError: division by zero`;

describe('offending line', () => {
  it('reads the line number of a simple traceback', () => {
    expect(parseTraceback(SIMPLE)).toEqual({ line: 3 });
  });

  it('also reads a syntax error, whose format differs', () => {
    // No traceback header, and the line is indented: an over-strict expression would let
    // precisely the most frequent case slip through.
    expect(parseTraceback(SYNTAX)).toEqual({ line: 1 });
  });

  it('keeps the deepest frame, that is to say the last one', () => {
    // Taking the first match would point at the caller — a perfectly innocent line.
    expect(parseTraceback(NESTED)).toEqual({ line: 5 });
  });

  it('returns null when there is no cell to point at', () => {
    expect(parseTraceback('KeyboardInterrupt')).toBeNull();
    expect(parseTraceback('')).toBeNull();
  });
});

describe('offset of a selection', () => {
  it('places the fragment line back into the file', () => {
    // "Run selection" sends a fragment whose line 1 is line 40 of the file.
    expect(editorLine({ line: 3 }, 39)).toBe(42);
  });

  it('leaves the line untouched for a whole buffer', () => {
    expect(editorLine({ line: 3 }, 0)).toBe(3);
  });
});
