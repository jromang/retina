// Console history navigation, and the echo bridge into the transcript.
//
// Both share the same failure mode: they work the first time and degrade afterwards. The history
// filter by sliding onto an entry that no longer matches, the bridge by recopying everything from
// the start each time the panel remounts — and that last bug is what motivated moving it up to
// module level.

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const { nextMatch } = await import('../src/console/historyNav');
const { blocks, clearTranscript, pushEcho } = await import('../src/console/transcript');
const { emitEcho, onEcho } = await import('../src/state/store');

describe('colorizePython — fallback while Monaco is not loaded yet', () => {
  it('returns null before registerMonaco, so the caller shows raw text', async () => {
    // Monaco arrives through a dynamic import (~2.5 MB): the console opens and gets used before
    // that. An empty transcript in the meantime would be worse than uncolored text.
    const { colorizePython, highlightReady } = await import('../src/console/highlight');
    expect(highlightReady()).toBe(false);
    expect(colorizePython('app.open("a.fit")')).toBeNull();
  });
});

describe('nextMatch — history filtered by prefix', () => {
  const entries = ['app.open("a.fit")', 'print(1)', 'app.close()', 'x = 2'];

  it('walks back from the end when navigation starts', () => {
    expect(nextMatch(entries, null, '', 'older')).toBe(3);
    expect(nextMatch(entries, 3, '', 'older')).toBe(2);
  });

  it('offers only the entries starting with the prefix', () => {
    expect(nextMatch(entries, null, 'app.', 'older')).toBe(2);
    expect(nextMatch(entries, 2, 'app.', 'older')).toBe(0);
    // Nothing older left that matches: the caller keeps what it is already showing.
    expect(nextMatch(entries, 0, 'app.', 'older')).toBeNull();
  });

  it('walks back toward the present and signals the return to the buffer', () => {
    expect(nextMatch(entries, 0, 'app.', 'newer')).toBe(2);
    expect(nextMatch(entries, 2, 'app.', 'newer')).toBeNull();
  });

  it('returns null rather than looping on a prefix that matches nothing', () => {
    expect(nextMatch(entries, null, 'zzz', 'older')).toBeNull();
  });

  it('handles an empty history without blowing up', () => {
    expect(nextMatch([], null, '', 'older')).toBeNull();
    expect(nextMatch([], null, '', 'newer')).toBeNull();
  });
});

describe('echo bridge — one subscriber, at module level', () => {
  beforeEach(() => {
    clearTranscript();
  });

  it('delivers only once per subscriber, even when subscribed twice', () => {
    const seen: string[] = [];
    const listener = (code: string) => seen.push(code);

    const stop = onEcho(listener);
    const stopAgain = onEcho(listener); // the same one: a Set, hence a single subscription
    try {
      emitEcho('app.zoom_in()');
    } finally {
      stop();
      stopAgain();
    }

    expect(seen).toEqual(['app.zoom_in()']);
  });

  it('sends nothing more after unsubscribing', () => {
    const seen: string[] = [];
    const stop = onEcho((code) => seen.push(code));
    stop();

    emitEcho('app.close()');

    expect(seen).toEqual([]);
  });

  it('a relayed echo becomes a transcript block', () => {
    // The real bridge: `connectTranscript` does exactly this wiring, once, at startup — and not
    // inside a panel effect, which recopied everything on every remount.
    const stop = onEcho(pushEcho);
    try {
      emitEcho('app.zoom_in()');
      emitEcho('app.select_view("v1")');
    } finally {
      stop();
    }

    const echoes = blocks.value.filter((block) => block.kind === 'echo');
    expect(echoes.map((block) => block.text)).toEqual(['app.zoom_in()', 'app.select_view("v1")']);

    // And nothing more after unsubscribing: this is what distinguishes the module-level bridge
    // from the earlier per-mount cursor, which replayed the whole echo on every reopening.
    emitEcho('app.close()');
    expect(blocks.value.filter((block) => block.kind === 'echo')).toHaveLength(2);
  });
});
