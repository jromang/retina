// The state of the open scripts — the half of the editor that can really break without anyone
// noticing: tab allocation, the "modified" computation, and what "Run selection" actually
// sends to the console.

import { afterEach, describe, expect, it, vi } from 'vitest';

// Types are imported statically (they vanish at compile time); values stay as dynamic imports,
// after the `stubGlobal` calls the client module depends on.
import type { DiskState, ScriptDoc } from '../src/scripts/scripts';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const {
  adoptScript,
  baseName,
  checkDisk,
  closeScript,
  dedent,
  diskConflicts,
  diskDiverged,
  keepMyVersion,
  markSaved,
  newScript,
  openScripts,
  openScriptFromDisk,
  reloadedScript,
  restoreScripts,
  runnableSelection,
  saveScriptTo,
  scriptById,
  scriptText,
  serializeScripts,
  setScriptText,
} = await import('../src/scripts/scripts');

const { client } = await import('../src/api/client');
const { promptRequest } = await import('../src/ui/prompts');

describe('open documents', () => {
  it('numbers tabs and titles without ever reusing an id', () => {
    const a = newScript();
    const b = newScript();
    expect(a).not.toBe(b);
    expect(a.startsWith('script:')).toBe(true);
    expect(scriptById(a)?.title).not.toBe(scriptById(b)?.title);
    closeScript(a);
    closeScript(b);
  });

  it('brings an already open file to the front instead of duplicating it', () => {
    // Two tabs on the same path would hold two diverging buffers, and the second save would
    // silently overwrite the first.
    const first = adoptScript('/tmp/recipe.py', 'a = 1\n');
    const again = adoptScript('/tmp/recipe.py', 'a = 1\n');
    expect(again).toBe(first);
    expect(openScripts.value.filter((doc) => doc.path === '/tmp/recipe.py')).toHaveLength(1);
    closeScript(first);
  });

  it('title = file name, path kept', () => {
    const id = adoptScript('/data/night/stack.py', '');
    expect(scriptById(id)?.title).toBe('stack.py');
    expect(scriptById(id)?.path).toBe('/data/night/stack.py');
    closeScript(id);
  });

  it('releases its buffer on close', () => {
    const id = newScript('x = 1');
    closeScript(id);
    expect(scriptText(id)).toBe('');
    expect(scriptById(id)).toBeUndefined();
  });
});

describe('"modified" state', () => {
  it('arms on typing and disarms on returning to the saved text', () => {
    // Comparing against the text on disk rather than arming a boolean: undoing back to the
    // original content must clear the dot on the tab.
    const id = adoptScript('/tmp/a.py', 'a = 1\n');
    expect(scriptById(id)?.dirty).toBe(false);

    setScriptText(id, 'a = 2\n');
    expect(scriptById(id)?.dirty).toBe(true);

    setScriptText(id, 'a = 1\n');
    expect(scriptById(id)?.dirty).toBe(false);
    closeScript(id);
  });

  it('a save sets the new reference', () => {
    const id = newScript('print(1)');
    expect(scriptById(id)?.dirty).toBe(true);
    markSaved(id, '/tmp/saved.py');
    expect(scriptById(id)?.dirty).toBe(false);
    expect(scriptById(id)?.title).toBe('saved.py');
    closeScript(id);
  });
});

describe('run selection', () => {
  const source = 'def f():\n    a = 1\n    return a\n';

  it('takes the cursor line when there is no selection', () => {
    expect(runnableSelection(source, '', 2)).toBe('a = 1');
  });

  it('dedents: a line taken from a function body would raise an IndentationError', () => {
    expect(runnableSelection(source, '    a = 1\n    return a', 2)).toBe('a = 1\nreturn a');
  });

  it('leaves a selection already at level zero untouched', () => {
    expect(runnableSelection(source, 'def f():\n    a = 1', 1)).toBe('def f():\n    a = 1');
  });

  it('ignores blank lines when computing the common indentation', () => {
    expect(dedent('  a\n\n  b')).toBe('a\n\nb');
  });
});

describe('file name', () => {
  it('splits Windows paths as well as POSIX ones', () => {
    expect(baseName('/data/m31/stack.py')).toBe('stack.py');
    expect(baseName('C:\\data\\m31\\stack.py')).toBe('stack.py');
  });
});

// --- modification outside the application -----------------------------------
//
// The scenario behind everything that follows: the script is open here, and vim (or git, or a
// synced folder) rewrites it. Before, the next save overwrote it without a word.

/** A minimal document — `diskDiverged` is pure, it looks at nothing else. */
function doc(overrides: Partial<ScriptDoc> = {}): ScriptDoc {
  return {
    id: 'script:test',
    path: '/tmp/a.py',
    title: 'a.py',
    dirty: false,
    disk: { size: 10, mtime_ns: 1_700_000_000_000_000_000 },
    ...overrides,
  };
}

function stat(overrides: Partial<DiskState> = {}): DiskState {
  return { exists: true, size: 10, mtime_ns: 1_700_000_000_000_000_000, ...overrides };
}

/** Replaces `client.call` with a table of answers, and records what was called. */
function fakeRpc(responses: Record<string, unknown>): { calls: [string, unknown][] } {
  const calls: [string, unknown][] = [];
  vi.spyOn(client, 'call').mockImplementation(async (method: string, params?: unknown) => {
    calls.push([method, params]);
    if (!(method in responses)) throw new Error(`unexpected call: ${method}`);
    return responses[method] as never;
  });
  return { calls };
}

afterEach(() => {
  vi.restoreAllMocks();
  promptRequest.value?.resolve(null);
});

describe('disk divergence (pure function)', () => {
  it('an identical stamp does not diverge', () => {
    expect(diskDiverged(doc(), stat())).toBe(false);
  });

  it('different size or date: the file has changed', () => {
    expect(diskDiverged(doc(), stat({ size: 11 }))).toBe(true);
    // One millisecond apart, at equal size — the "I fix one letter" case. Writing +1 ns here
    // would prove nothing: beyond 2^53, `1.7e18 + 1` is the very same double as `1.7e18`
    // (cf. the comment on `DiskStamp`).
    expect(diskDiverged(doc(), stat({ mtime_ns: 1_700_000_000_001_000_000 }))).toBe(true);
  });

  it('with no known stamp, we conclude nothing', () => {
    // The case of a project saved before the field existed: unknown is not "changed",
    // otherwise every project reopening would ask a question on the first save.
    expect(diskDiverged(doc({ disk: null }), stat({ size: 999 }))).toBe(false);
    expect(diskDiverged(doc({ path: null }), stat({ size: 999 }))).toBe(false);
  });

  it('a file that has gone is not a divergence', () => {
    // Nothing to overwrite (the save recreates it), and above all nothing to reload: emptying
    // the buffer of a clean tab because the file was moved would be the worst outcome of all.
    expect(diskDiverged(doc(), stat({ exists: false, size: 0, mtime_ns: 0 }))).toBe(false);
  });
});

describe('recorded stamp', () => {
  it('an open records what was on disk', async () => {
    fakeRpc({
      'fs.read_text': { path: '/tmp/opened.py', text: 'a = 1\n', size: 6, mtime_ns: 42 },
    });
    const id = await openScriptFromDisk('~/opened.py');
    expect(scriptById(id)?.disk).toEqual({ size: 6, mtime_ns: 42 });
    closeScript(id);
  });

  it('a save records the stamp of what it has just written', async () => {
    fakeRpc({ 'fs.write_text': { path: '/tmp/fresh.py', size: 8, mtime_ns: 7 } });
    const id = newScript('print(1)');
    expect(await saveScriptTo(id, '/tmp/fresh.py')).toBe(true);
    expect(scriptById(id)?.disk).toEqual({ size: 8, mtime_ns: 7 });
    expect(scriptById(id)?.dirty).toBe(false);
    closeScript(id);
  });
});

describe('saving over an outside modification', () => {
  async function waitForModal(): Promise<void> {
    await vi.waitFor(() => expect(promptRequest.value).not.toBeNull());
  }

  it('asks for confirmation, and writes nothing if we back out', async () => {
    const { calls } = fakeRpc({ 'fs.stat': stat({ size: 99 }) });
    const id = adoptScript('/tmp/conflict.py', 'a = 1\n', { size: 10, mtime_ns: 1 });
    setScriptText(id, 'a = 2\n');

    const inFlight = saveScriptTo(id, '/tmp/conflict.py');
    await waitForModal();
    promptRequest.value?.resolve(null); // "Cancel"

    expect(await inFlight).toBe(false);
    expect(calls.map(([method]) => method)).toEqual(['fs.stat']);
    // The buffer is intact and still marked modified: nothing was lost, on either side.
    expect(scriptText(id)).toBe('a = 2\n');
    expect(scriptById(id)?.dirty).toBe(true);
    closeScript(id);
  });

  it('writes if we confirm, and adopts the new stamp', async () => {
    const { calls } = fakeRpc({
      'fs.stat': stat({ size: 99 }),
      'fs.write_text': { path: '/tmp/conflict.py', size: 6, mtime_ns: 123 },
    });
    const id = adoptScript('/tmp/conflict.py', 'a = 1\n', { size: 10, mtime_ns: 1 });
    setScriptText(id, 'a = 2\n');

    const inFlight = saveScriptTo(id, '/tmp/conflict.py');
    await waitForModal();
    promptRequest.value?.resolve(''); // "Overwrite"

    expect(await inFlight).toBe(true);
    expect(calls.map(([method]) => method)).toEqual(['fs.stat', 'fs.write_text']);
    expect(scriptById(id)?.disk).toEqual({ size: 6, mtime_ns: 123 });
    closeScript(id);
  });

  it('asks nothing for a "save as" towards another file', async () => {
    // The known stamp does not describe that file; warning about an overwrite is the native
    // dialog's job, as it is everywhere else.
    const { calls } = fakeRpc({ 'fs.write_text': { path: '/tmp/other.py', size: 6, mtime_ns: 5 } });
    const id = adoptScript('/tmp/source.py', 'a = 1\n', { size: 10, mtime_ns: 1 });
    expect(await saveScriptTo(id, '/tmp/other.py')).toBe(true);
    expect(calls.map(([method]) => method)).toEqual(['fs.write_text']);
    closeScript(id);
  });
});

describe('coming back to the tab', () => {
  it('clean tab + changed file: silent reload', async () => {
    fakeRpc({
      'fs.stat': stat({ size: 99, mtime_ns: 2 }),
      'fs.read_text': { path: '/tmp/outside.py', text: 'b = 2\n', size: 6, mtime_ns: 2 },
    });
    const id = adoptScript('/tmp/outside.py', 'a = 1\n', { size: 10, mtime_ns: 1 });
    const before = reloadedScript.value?.seq ?? 0;

    expect(await checkDisk(id)).toBe('reloaded');
    expect(scriptText(id)).toBe('b = 2\n');
    expect(scriptById(id)?.dirty).toBe(false);
    expect(scriptById(id)?.disk).toEqual({ size: 6, mtime_ns: 2 });
    // The editor is told: without that signal, Monaco would keep displaying the old text.
    expect(reloadedScript.value).toEqual({ id, seq: before + 1 });
    closeScript(id);
  });

  it('modified tab + changed file: banner, and not a line lost', async () => {
    fakeRpc({ 'fs.stat': stat({ size: 99, mtime_ns: 2 }) });
    const id = adoptScript('/tmp/two.py', 'a = 1\n', { size: 10, mtime_ns: 1 });
    setScriptText(id, 'a = 2\n');

    expect(await checkDisk(id)).toBe('conflict');
    expect(diskConflicts.value).toContain(id);
    expect(scriptText(id)).toBe('a = 2\n');
    closeScript(id);
    // Closing the tab drops the conflict: a banner with no document has nothing to sit on.
    expect(diskConflicts.value).not.toContain(id);
  });

  it('unchanged file: nothing, whatever the state of the buffer', async () => {
    fakeRpc({ 'fs.stat': stat({ size: 10, mtime_ns: 1 }) });
    const id = adoptScript('/tmp/stable.py', 'a = 1\n', { size: 10, mtime_ns: 1 });
    expect(await checkDisk(id)).toBe('unchanged');
    setScriptText(id, 'a = 2\n');
    expect(await checkDisk(id)).toBe('unchanged');
    expect(diskConflicts.value).not.toContain(id);
    closeScript(id);
  });

  it('with no known stamp, we do not touch the disk', async () => {
    const { calls } = fakeRpc({});
    const id = newScript('a = 1\n');
    expect(await checkDisk(id)).toBe('unknown');
    expect(calls).toEqual([]);
    closeScript(id);
  });

  it('"keep my version" adopts the stamp: the question does not come back', async () => {
    fakeRpc({
      'fs.stat': stat({ size: 99, mtime_ns: 2 }),
      'fs.write_text': { path: '/tmp/keep.py', size: 6, mtime_ns: 3 },
    });
    const id = adoptScript('/tmp/keep.py', 'a = 1\n', { size: 10, mtime_ns: 1 });
    setScriptText(id, 'a = 2\n');
    expect(await checkDisk(id)).toBe('conflict');

    await keepMyVersion(id);
    expect(diskConflicts.value).not.toContain(id);
    // The next save writes with no modal: the decision has already been taken once.
    expect(await saveScriptTo(id, '/tmp/keep.py')).toBe(true);
    expect(promptRequest.value).toBeNull();
    closeScript(id);
  });
});

describe('persisting the stamp in a project', () => {
  it('the stamp makes the round trip', () => {
    const id = adoptScript('/tmp/project.py', 'a = 1\n', { size: 10, mtime_ns: 1 });
    const state = serializeScripts();
    expect(state.docs.find((d) => d.id === id)?.disk).toEqual({ size: 10, mtime_ns: 1 });
    restoreScripts(state);
    expect(scriptById(id)?.disk).toEqual({ size: 10, mtime_ns: 1 });
    closeScript(id);
  });

  it('a project written before this field reloads without error', () => {
    // The field is optional: its absence means "unknown", not an exception.
    restoreScripts({
      docs: [{ id: 'script:99', path: '/tmp/legacy.py', title: 'legacy.py',
               text: 'a = 1\n', savedText: 'a = 1\n' }],
      nextId: 100,
      nextUntitled: 1,
      activeId: 'script:99',
    });
    expect(scriptById('script:99')?.disk).toBeNull();
    closeScript('script:99');
  });
});
