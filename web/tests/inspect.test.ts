// Hover, signature help and "script from history" — the pure logic behind all three.
//
// Parameter counting is the part that breaks silently: one nested comma shifts the highlight by
// a slot, and nothing on screen says so except the wrong parameter shown in bold. Hence the
// insistence on nested cases.

import { describe, expect, it, vi } from 'vitest';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const { callContext, splitParameters } = await import('../src/console/inspect');
const { scriptFromBlocks } = await import('../src/console/historyScript');
type Block = import('../src/console/transcript').Block;

/** `|` marks the cursor position — more readable than a numeric offset. */
function at(source: string) {
  const cursor = source.indexOf('|');
  return callContext(source.replace('|', ''), cursor);
}

describe('call surrounding the cursor', () => {
  it('targets the callee name, not the cursor', () => {
    // The server expands its symbol around the offset it receives: between the parentheses it
    // would find nothing but the argument currently being typed.
    const context = at('app.open(|)');
    expect(context?.calleeEnd).toBe('app.open'.length);
    expect(context?.activeParameter).toBe(0);
  });

  it('counts the parameters at the current level', () => {
    expect(at('f(1, 2, |)')?.activeParameter).toBe(2);
  });

  it('ignores commas belonging to a nested call', () => {
    const context = at('f(g(1, 2), |)');
    expect(context?.activeParameter).toBe(1);
    expect(context?.calleeEnd).toBe(1);
  });

  it('ignores commas inside a list or a dictionary', () => {
    expect(at('f([1, 2, 3], |)')?.activeParameter).toBe(1);
    expect(at('f({"a": 1, "b": 2}, |)')?.activeParameter).toBe(1);
  });

  it('ignores commas inside a string', () => {
    expect(at('f("a, b", |)')?.activeParameter).toBe(1);
  });

  it('offers nothing outside a call', () => {
    expect(at('a = 1|')).toBeNull();
    expect(at('f(1, 2)|')).toBeNull();
    expect(at('[1, 2, |]')).toBeNull();
  });
});

describe('splitting a signature', () => {
  it('separates simple parameters', () => {
    expect(splitParameters('f(a, b=2, *args, **kw)')).toEqual(['a', 'b=2', '*args', '**kw']);
  });

  it('does not invent a parameter out of a compound default value', () => {
    expect(splitParameters('f(a, b=g(1, 2), c=[3, 4])')).toEqual(['a', 'b=g(1, 2)', 'c=[3, 4]']);
  });

  it('returns an empty list for a signature with no parameters, or an unreadable one', () => {
    expect(splitParameters('f()')).toEqual([]);
    expect(splitParameters('a module')).toEqual([]);
  });

  it('stops at the matching parenthesis, not at the last one in the text', () => {
    // IPython appends the return annotation, and it may itself carry parentheses.
    expect(splitParameters("app.open(path: 'str') -> 'ImageWindow'")).toEqual(["path: 'str'"]);
    expect(splitParameters('f(a) -> g(int)')).toEqual(['a']);
  });
});

describe('script from history', () => {
  let id = 0;
  const block = (kind: Block['kind'], text: string): Block => ({ id: ++id, kind, text });

  it('keeps the inputs and the echo, in order, and nothing else', () => {
    const script = scriptFromBlocks(
      [
        block('input', 'a = 1'),
        block('stdout', 'noise'),
        block('echo', "app.open('m31.fits')"),
        block('result', '42'),
        block('error', 'Traceback…'),
        block('input', 'b = 2'),
      ],
      '2026-07-26',
    );
    const code = script.split('\n').filter((line) => line && !line.startsWith('#'));
    expect(code).toEqual(['a = 1', "app.open('m31.fits')", 'b = 2']);
  });

  it('neutralizes what only exists inside the console', () => {
    // `exec` on a file knows neither magics nor the trailing `?`: leaving them as-is would make
    // the recipe fail on its very first line.
    const script = scriptFromBlocks(
      [block('input', '%timeit f()'), block('input', 'app.open?'), block('input', '!ls')],
      '2026-07-26',
    );
    expect(script).not.toMatch(/^\s*%timeit/m);
    expect(script).not.toMatch(/^\s*!ls/m);
    expect(script).toContain('# (console only) app.open?');
  });

  it('writes nothing but a header for an empty session', () => {
    const script = scriptFromBlocks([], '2026-07-26');
    expect(script.split('\n').every((line) => !line || line.startsWith('#'))).toBe(true);
  });
});
