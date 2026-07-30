// A project's document blob — what the server carries around without understanding it.
//
// What can actually break unnoticed: an unsaved buffer lost, an id counter running backwards and
// manufacturing tab collisions, an unknown version half-replacing the current session.

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const memory = new Map<string, string>();
vi.stubGlobal('localStorage', {
  getItem: (k: string) => memory.get(k) ?? null,
  setItem: (k: string, v: string) => void memory.set(k, v),
  removeItem: (k: string) => void memory.delete(k),
});

const {
  DOCUMENTS_VERSION,
  restoreDocuments,
  serializeDocuments,
  setDockProvider,
  takePendingActiveTab,
} = await import('../src/project/documents');
const {
  closeScript,
  newScript,
  openScripts,
  activeScriptId,
  scriptById,
  scriptCursor,
  scriptText,
  setScriptCursor,
  setScriptText,
  markSaved,
} = await import('../src/scripts/scripts');
const { newContainer, openContainers, setSteps, containerById } = await import(
  '../src/pipeline/containerEdit'
);
const { blocks, pushEcho, clearTranscript } = await import('../src/console/transcript');
const { filesRoot, setFilesRoot } = await import('../src/panels/filesRoot');

function clearAll(): void {
  for (const doc of [...openScripts.value]) closeScript(doc.id);
  openContainers.value = [];
  clearTranscript();
  setFilesRoot(null);
  setDockProvider(null);
}

beforeEach(clearAll);

describe('round trip', () => {
  it('keeps an unsaved buffer and recomputes "dirty"', () => {
    const id = newScript();
    setScriptText(id, 'x = 1\n');
    expect(scriptById(id)?.dirty).toBe(true);

    const blob = serializeDocuments();
    clearAll();
    expect(restoreDocuments(blob)).toBe(true);

    expect(scriptText(id)).toBe('x = 1\n');
    expect(scriptById(id)?.dirty).toBe(true);
  });

  it('a script identical to its file does not come back marked dirty', () => {
    const id = newScript();
    setScriptText(id, 'print(1)\n');
    markSaved(id, '/tmp/a.py');

    const blob = serializeDocuments();
    clearAll();
    restoreDocuments(blob);

    expect(scriptById(id)?.dirty).toBe(false);
    expect(scriptById(id)?.path).toBe('/tmp/a.py');
  });

  it('keeps the cursor position', () => {
    const id = newScript();
    setScriptText(id, 'a\nb\nc\n');
    setScriptCursor(id, { lineNumber: 3, column: 2 });

    const blob = serializeDocuments();
    clearAll();
    restoreDocuments(blob);

    expect(scriptCursor(id)).toEqual({ lineNumber: 3, column: 2 });
  });

  it('keeps recipes with their disabled steps and their masks', () => {
    const id = newContainer();
    setSteps(id, [
      { process_id: 'Invert', values: {}, enabled: false },
      { process_id: 'Rescale', values: { low: 0.1 }, mask: 'Mask01', mask_inverted: true },
    ]);

    const blob = serializeDocuments();
    clearAll();
    restoreDocuments(blob);

    const doc = containerById(id);
    expect(doc?.steps[0]?.enabled).toBe(false);
    expect(doc?.steps[1]?.mask).toBe('Mask01');
    expect(doc?.steps[1]?.mask_inverted).toBe(true);
    expect(doc?.dirty).toBe(true);
  });

  it('keeps the explorer root — a project reopens ITS working folder', () => {
    setFilesRoot('/data/m31');

    const blob = serializeDocuments();
    setFilesRoot('/elsewhere');
    restoreDocuments(blob);

    expect(filesRoot.value).toBe('/data/m31');
  });

  it('keeps the transcript, echo blocks included', () => {
    pushEcho('app.open("/data/m31.fits")');

    const blob = serializeDocuments();
    clearTranscript();
    restoreDocuments(blob);

    expect(blocks.value.map((b) => b.text)).toContain('app.open("/data/m31.fits")');
    expect(blocks.value.every((b) => typeof b.id === 'number')).toBe(true);
  });

  it('bounds the transcript — it has no business weighing down a project file', () => {
    for (let i = 0; i < 600; i++) pushEcho(`line ${i}`);

    expect(serializeDocuments().transcript.length).toBe(400);
  });
});

describe('counters', () => {
  it('a new script after a restore does not reuse an id already taken', () => {
    const a = newScript();
    const b = newScript();

    const blob = serializeDocuments();
    clearAll();
    restoreDocuments(blob);
    const c = newScript();

    expect(c).not.toBe(a);
    expect(c).not.toBe(b);
  });

  it('restoring twice does not make the counters run backwards', () => {
    newScript();
    newScript();
    const blob = serializeDocuments();
    clearAll();
    newScript(); // the current session has already moved on
    const advanced = openScripts.value[0]?.id;

    restoreDocuments(blob);
    restoreDocuments(blob);
    const next = newScript();

    expect(next).not.toBe(advanced);
    expect(openScripts.value.some((doc) => doc.id === next)).toBe(true);
  });
});

describe('robustness', () => {
  it('an unknown version touches nothing rather than half-replacing', () => {
    const id = newScript();
    setScriptText(id, 'keep-me\n');
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    const applied = restoreDocuments({ version: 99, scripts: { docs: [] } });

    expect(applied).toBe(false);
    expect(scriptText(id)).toBe('keep-me\n');
    warning.mockRestore();
  });

  it('a missing or malformed blob is rejected without throwing', () => {
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    expect(restoreDocuments(null)).toBe(false);
    expect(restoreDocuments({ version: DOCUMENTS_VERSION })).toBe(false);

    warning.mockRestore();
  });

  it('deduplicates two tabs on the same path', () => {
    // Two tabs on the same file would hold two diverging buffers, and one save would overwrite
    // the other.
    const blob = serializeDocuments();
    blob.scripts.docs = [
      { id: 'script:1', path: '/a.py', title: 'a.py', text: 'x', savedText: 'x' },
      { id: 'script:2', path: '/a.py', title: 'a.py', text: 'y', savedText: 'y' },
    ];

    restoreDocuments(blob);

    expect(openScripts.value.length).toBe(1);
    expect(openScripts.value[0]?.id).toBe('script:1');
  });

  it('an active tab that no longer exists leaves no phantom target', () => {
    const blob = serializeDocuments();
    blob.scripts.docs = [];
    blob.scripts.activeId = 'script:42';

    restoreDocuments(blob);

    expect(activeScriptId.value).toBeNull();
  });
});

describe('active tab', () => {
  it('is set aside, not applied straight away', () => {
    // Applying it immediately would achieve nothing: the tabs do not exist yet on the dockview
    // side, and the last one added would steal the foreground.
    setDockProvider(() => ({ activeTab: 'script:1' }));
    const blob = serializeDocuments();

    expect(blob.activeTab).toBe('script:1');

    restoreDocuments(blob);
    expect(takePendingActiveTab()).toBe('script:1');
    expect(takePendingActiveTab()).toBeNull(); // consumed exactly once
  });

  it('is filled in BEFORE the signals that trigger reconciliation', () => {
    // Bug found in e2e: set after `restoreScripts`, an intermediate reconciliation found it
    // empty and the last tab added kept the foreground.
    setDockProvider(() => ({ activeTab: 'script:7' }));
    const blob = serializeDocuments();
    let seenDuringRestore: string | null = null;
    const unsubscribe = openScripts.subscribe(() => {
      seenDuringRestore ??= takePendingActiveTab();
    });

    restoreDocuments(blob);
    unsubscribe();

    expect(seenDuringRestore).toBe('script:7');
  });

  it('stays a valid blob with no dock provider', () => {
    const blob = serializeDocuments();

    expect(blob.activeTab).toBeNull();
    expect(restoreDocuments(blob)).toBe(true);
  });
});
