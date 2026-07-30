// State of the open scripts — the testable half of the editor, without DOM or Monaco.
//
// # Why this state lives on the client
//
// A script tab is **chrome**, in the same way as the size of the zones or the decorations of
// the native window: it is not a domain action. The console equivalent of opening a script is
// not an `app.*` to invent, it is `open(path).read()` — and running it is `app.run_recipe(path)`,
// which has always existed. The parity pillar is therefore upheld without a new application
// object.
//
// The transport, on the other hand, is very much server-side: `fs.read_text`/`fs.write_text`.
// Files live on the Python side, like images — in browser or remote mode, the client's disk has
// nothing to do with the one running the scripts.
//
// # The text is here, not only in Monaco
//
// The Monaco model remains the editing source, but its content is copied here on every
// keystroke. That is what lets "Save" and "Run" start from a palette command without the
// registry having to know about a mounted component — and it is what makes the logic testable
// without a browser.

import { signal } from '@preact/signals';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import { busy, execute, type RunOrigin } from '../console/transcript';
import { pushToast } from '../notifications/store';
import { requestActivate } from '../shell/layoutClient';
import { SCRIPT_FILTERS, askPath } from '../shell/native';
import { confirmBox } from '../ui/prompts';

export const SCRIPT_PREFIX = 'script:';

/**
 * Fingerprint of a file on disk — the pair `fs.*` returns (cf. `handlers_fs.py`).
 *
 * `mtime_ns` is about 1.7e18, beyond the 2^53 exact integers of a `number`: `JSON.parse`
 * rounds it. This has no consequence here because we never do arithmetic on it, only an
 * **equality** between two values that went through the same rounding. The only case lost
 * would be two writes less than ~256 ns apart and of identical size — far below the resolution
 * of any file system.
 */
export interface DiskStamp {
  size: number;
  mtime_ns: number;
}

/** Response of `fs.stat`: the fingerprint, plus whether the file still exists. */
export interface DiskState extends DiskStamp {
  exists: boolean;
}

export interface ScriptDoc {
  /** dockview tab id: `script:<n>`. Stable for the whole life of the document. */
  id: string;
  /** Path on the server's disk, `null` as long as the script has never been saved. */
  path: string | null;
  title: string;
  dirty: boolean;
  /**
   * Fingerprint of the file as we left it — set on opening and on every save. `null` =
   * **unknown**, never "unchanged": that is the case of a script never saved, and that of a
   * project written before this field existed. An unknown state triggers nothing — neither a
   * question on save nor a reload — because comparing against a reference one does not have
   * can only produce false positives.
   */
  disk: DiskStamp | null;
}

export const openScripts = signal<readonly ScriptDoc[]>([]);
/** Last script tab brought to the front — the target of the palette commands. */
export const activeScriptId = signal<string | null>(null);

/** Current text, keyed by id. Not reactive: while typing, only `dirty` can change. */
const buffers = new Map<string, string>();
/** Text as it is on disk — the reference that defines "modified". */
const saved = new Map<string, string>();
/**
 * Cursor position, keyed by id.
 *
 * Outside the signal, deliberately, and for the same reason as `buffers`: the signal only moves
 * when `dirty` flips, otherwise every keystroke would redraw the tabs. An arrow key moves the
 * cursor dozens of times per second; putting it in `ScriptDoc` would replay the dock
 * reconciliation each time.
 */
const cursors = new Map<string, CursorPosition>();

export interface CursorPosition {
  lineNumber: number;
  column: number;
}

let nextId = 1;
let nextUntitled = 1;

export function baseName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function patch(id: string, changes: Partial<ScriptDoc>): void {
  openScripts.value = openScripts.value.map((doc) =>
    doc.id === id ? { ...doc, ...changes } : doc,
  );
}

export function scriptById(id: string): ScriptDoc | undefined {
  return openScripts.value.find((doc) => doc.id === id);
}

export function scriptText(id: string): string {
  return buffers.get(id) ?? '';
}

/** Text as it is on disk — what `dirty` compares against. */
export function savedScriptText(id: string): string {
  return saved.get(id) ?? '';
}

export function scriptCursor(id: string): CursorPosition | null {
  return cursors.get(id) ?? null;
}

export function setScriptCursor(id: string, position: CursorPosition): void {
  cursors.set(id, position);
}

/**
 * Copies the editor text and recomputes the "modified" state.
 *
 * Comparing against the saved text rather than arming a boolean: undoing back to the original
 * content clears the tab's dot, which is the expected behavior and costs nothing. The signal is
 * touched only when the state flips — otherwise every keystroke would redraw the tabs.
 */
export function setScriptText(id: string, text: string): void {
  buffers.set(id, text);
  const doc = scriptById(id);
  if (!doc) return;
  const dirty = text !== (saved.get(id) ?? '');
  if (dirty !== doc.dirty) patch(id, { dirty });
}

export function newScript(text = '', title = ''): string {
  const id = `${SCRIPT_PREFIX}${nextId++}`;
  buffers.set(id, text);
  saved.set(id, '');
  openScripts.value = [
    ...openScripts.value,
    {
      id,
      path: null,
      title: title || m.script_untitled({ n: nextUntitled++ }),
      dirty: text !== '',
      disk: null,
    },
  ];
  activeScriptId.value = id;
  return id;
}

/**
 * Opens a script that has already been read. A file already open is brought to the front rather
 * than duplicated — two tabs on the same path would have two diverging buffers and a save that
 * would overwrite the other.
 */
export function adoptScript(path: string, text: string, disk: DiskStamp | null = null): string {
  const existing = openScripts.value.find((doc) => doc.path === path);
  if (existing) {
    activeScriptId.value = existing.id;
    return existing.id;
  }
  const id = `${SCRIPT_PREFIX}${nextId++}`;
  buffers.set(id, text);
  saved.set(id, text);
  openScripts.value = [
    ...openScripts.value,
    { id, path, title: baseName(path), dirty: false, disk },
  ];
  activeScriptId.value = id;
  return id;
}

export function closeScript(id: string): void {
  buffers.delete(id);
  saved.delete(id);
  cursors.delete(id);
  clearConflict(id);
  openScripts.value = openScripts.value.filter((doc) => doc.id !== id);
  if (activeScriptId.value === id) activeScriptId.value = openScripts.value.at(-1)?.id ?? null;
}

// --- persistence (project) -------------------------------------------------

/** A script tab as a project carries it. */
export interface SerializedScript {
  id: string;
  path: string | null;
  title: string;
  text: string;
  savedText: string;
  cursor?: CursorPosition;
  /**
   * Known disk fingerprint. **Optional**: a project written before this field existed must be
   * read back without error — its absence means "unknown", and the restored tab will simply
   * ask no question until it has been saved.
   */
  disk?: DiskStamp;
}

export interface SerializedScripts {
  docs: SerializedScript[];
  nextId: number;
  nextUntitled: number;
  activeId: string | null;
}

export function serializeScripts(): SerializedScripts {
  return {
    docs: openScripts.value.map((doc) => {
      const cursor = cursors.get(doc.id);
      const base: SerializedScript = {
        id: doc.id,
        path: doc.path,
        title: doc.title,
        text: scriptText(doc.id),
        // The disk text travels too: `dirty` will be **recomputed** on restore. Carrying the
        // boolean would leave a tab marked modified whose content is nevertheless identical to
        // the file, or the reverse — more wrong still.
        savedText: savedScriptText(doc.id),
        ...(doc.disk ? { disk: doc.disk } : {}),
      };
      return cursor ? { ...base, cursor } : base;
    }),
    nextId,
    nextUntitled,
    activeId: activeScriptId.value,
  };
}

/**
 * Replaces the script tabs with those of a project.
 *
 * The counters are taken with `Math.max`: a restore played twice (notification then `hello`,
 * for instance) must not make them go backwards, otherwise the next "new script" would receive
 * an id already taken — and tab ids are what dockview refers to.
 *
 * The Monaco models of the documents that disappeared are disposed of by `ScriptTab`, which
 * already observes `openScripts`. The undo stack, however, is lost: a model recreated from its
 * text has no history. That is accepted — the content itself is intact.
 */
export function restoreScripts(state: SerializedScripts): void {
  buffers.clear();
  saved.clear();
  cursors.clear();
  const docs: ScriptDoc[] = [];
  for (const doc of state.docs) {
    if (docs.some((existing) => doc.path !== null && existing.path === doc.path)) continue;
    buffers.set(doc.id, doc.text);
    saved.set(doc.id, doc.savedText);
    if (doc.cursor) cursors.set(doc.id, doc.cursor);
    docs.push({
      id: doc.id,
      path: doc.path,
      title: doc.title,
      dirty: doc.text !== doc.savedText,
      disk: doc.disk ?? null,
    });
  }
  diskConflicts.value = [];
  openScripts.value = docs;
  nextId = Math.max(nextId, state.nextId ?? 1);
  nextUntitled = Math.max(nextUntitled, state.nextUntitled ?? 1);
  activeScriptId.value = docs.some((doc) => doc.id === state.activeId) ? state.activeId : null;
}

/** Marks the document as saved at that path — clears the tab's dot. */
export function markSaved(id: string, path: string, disk: DiskStamp | null = null): void {
  saved.set(id, scriptText(id));
  patch(id, { path, title: baseName(path), dirty: false, disk });
}

// --- disk ------------------------------------------------------------------
//
// # External modification: check at the right moment, not all the time
//
// A script open here can be rewritten by vim, by git, by a script. With nothing in place, the
// next save overwrote it **silently**, and a clean tab displayed stale content indefinitely.
// The doctrine is written at the head of `handlers_fs.py`: no file system watcher, but a
// `(size, mtime_ns)` fingerprint taken at the two moments when the user really looks at that
// buffer — **before writing**, and **on returning to the tab or to the window**. Zero cost the
// rest of the time, and not one more dependency.
//
// The four cases, and nothing else:
//   clean + unchanged  → nothing;
//   clean + changed    → silent reload + notification (there is nothing to lose);
//   dirty + changed    → non-modal banner in the editor (reload / keep my version);
//   dirty + unchanged  → nothing, this is ordinary editing.
// And on save, a divergence opens an overwrite confirmation: the only moment a modal is
// justified, since we are about to destroy someone else's work.

interface WriteResponse extends DiskStamp {
  path: string;
}

interface ReadResponse extends WriteResponse {
  text: string;
}

/** Ids of the documents whose file diverged while the buffer was modified. */
export const diskConflicts = signal<readonly string[]>([]);

/**
 * Last reload performed, so that the editor can realign its Monaco model.
 *
 * A signal rather than a direct call: `scripts.ts` does not know about Monaco (that is what
 * makes it testable without a browser), and `ScriptTab` already observes signals. The `seq`
 * counter is what tells two successive reloads of the same document apart.
 */
export const reloadedScript = signal<{ id: string; seq: number } | null>(null);
let reloadSeq = 0;

function stampOf(response: DiskStamp): DiskStamp {
  return { size: response.size, mtime_ns: response.mtime_ns };
}

export function hasDiskConflict(id: string): boolean {
  return diskConflicts.value.includes(id);
}

function markConflict(id: string): void {
  if (!hasDiskConflict(id)) diskConflicts.value = [...diskConflicts.value, id];
}

function clearConflict(id: string): void {
  if (hasDiskConflict(id)) diskConflicts.value = diskConflicts.value.filter((x) => x !== id);
}

/**
 * Has the file changed under our feet? A **pure** function — all the judgment lives here.
 *
 * Two `false` returns that deserve their line. Without a known fingerprint (new script, old
 * project), we know nothing: claiming otherwise would ask a question on every save. A file
 * that has **disappeared** is not a divergence either: there is nothing to overwrite (the save
 * recreates it) and nothing to reload — treating the disappearance as a change would empty the
 * buffer of a clean tab, which would be the worst possible reaction.
 */
export function diskDiverged(doc: ScriptDoc, stat: DiskState): boolean {
  if (!doc.path || !doc.disk || !stat.exists) return false;
  return stat.size !== doc.disk.size || stat.mtime_ns !== doc.disk.mtime_ns;
}

/** Current fingerprint of a file, without reading it. */
export function statFile(path: string): Promise<DiskState> {
  return client.call<DiskState>('fs.stat', { path });
}

export async function openScriptFromDisk(path: string): Promise<string> {
  const response = await client.call<ReadResponse>('fs.read_text', { path });
  // The server returns the **resolved** path: that is what must serve as the key, otherwise
  // `~/a.py` and `/home/x/a.py` would open two tabs on the same file.
  return adoptScript(response.path, response.text, stampOf(response));
}

/** Re-reads the file and replaces the buffer — the local content is discarded. */
export async function reloadFromDisk(id: string): Promise<boolean> {
  const doc = scriptById(id);
  if (!doc?.path) return false;
  const response = await client.call<ReadResponse>('fs.read_text', { path: doc.path });
  buffers.set(id, response.text);
  saved.set(id, response.text);
  clearConflict(id);
  patch(id, { dirty: false, disk: stampOf(response) });
  reloadedScript.value = { id, seq: ++reloadSeq };
  return true;
}

/**
 * "Keep my version" resolution: the banner goes away, the buffer does not move.
 *
 * The disk fingerprint is **adopted** in passing. That is the subtle point: the decision to
 * ignore the external version is taken once, and the next save must not ask the same question
 * again — otherwise the user learns to click "overwrite" without reading.
 */
export async function keepMyVersion(id: string): Promise<void> {
  const doc = scriptById(id);
  clearConflict(id);
  if (!doc?.path) return;
  const stat = await statFile(doc.path);
  patch(id, { disk: stat.exists ? stampOf(stat) : null });
}

export type DiskCheck = 'unknown' | 'unchanged' | 'reloaded' | 'conflict';

/**
 * Confronts a tab with its file. Called on returning to the tab and on window focus.
 *
 * Never asks anything: a clean tab is reloaded and the user is *informed* (the content they
 * were looking at no longer existed); a modified tab raises a banner, which they can ignore for
 * as long as they like. A modal at that moment would interrupt a gesture the user did not
 * initiate.
 */
export async function checkDisk(id: string): Promise<DiskCheck> {
  const doc = scriptById(id);
  if (!doc?.path || !doc.disk) return 'unknown';
  const stat = await statFile(doc.path);
  if (!diskDiverged(doc, stat)) return 'unchanged';
  if (doc.dirty) {
    markConflict(id);
    return 'conflict';
  }
  await reloadFromDisk(id);
  pushToast('info', m.script_reloaded({ name: doc.title }));
  return 'reloaded';
}

/**
 * Writes the buffer. Returns `false` when nothing was written — including a user refusal.
 *
 * The check applies only to the **document's** file: a "Save as" to another path is a
 * deliberate write, and it is up to the native dialog to warn about an overwrite, as in any
 * other application.
 */
export async function saveScriptTo(id: string, path: string): Promise<boolean> {
  const doc = scriptById(id);
  if (doc && doc.path === path && doc.disk) {
    const stat = await statFile(path);
    if (diskDiverged(doc, stat)) {
      const overwrite = await confirmBox(
        m.script_disk_changed_save({ name: doc.title }),
        m.prompt_overwrite(),
      );
      if (!overwrite) return false;
    }
  }
  const response = await client.call<WriteResponse>('fs.write_text', {
    path,
    text: scriptText(id),
  });
  clearConflict(id);
  markSaved(id, response.path, stampOf(response));
  return true;
}

/** Saves — asks for a path if the script does not have one yet, or if forced. */
export async function saveScript(id: string, forcePath = false): Promise<boolean> {
  const doc = scriptById(id);
  if (!doc) return false;
  let path = doc.path;
  if (!path || forcePath) {
    const chosen = await askPath({
      title: m.script_save_dialog(),
      save: true,
      filters: SCRIPT_FILTERS,
      filename: doc.path ? doc.title : `${doc.title}.py`,
    });
    if (!chosen?.[0]) return false;
    path = chosen[0];
  }
  return saveScriptTo(id, path);
}

// --- execution -------------------------------------------------------------

/**
 * Executes code in the **shared** console — the buffer, not the file.
 *
 * The transcript's `execute()`, and not a direct `console.execute`: it is what pushes the input
 * block, arms the busy indicator and lets `console.stream` interleave the output. A direct RPC
 * call would indeed run the code, but without leaving a readable trace.
 *
 * What makes this gesture irreplaceable: the variables stay available at the prompt. That is
 * the point of an editor attached to a live session, and what `runFile` below deliberately does
 * not do.
 *
 * The console is opened in passing — running a script whose output one could not see would be a
 * gesture without a return. `layout.activate` rather than a local setting: it is a layout
 * action, hence echoed like the others.
 *
 * Returns `false` when nothing was started (empty buffer, or execution already in progress).
 */
export function runInConsole(code: string, origin: RunOrigin | null = null): boolean {
  if (!code.trim() || busy.value) return false;
  requestActivate('console');
  void execute(code, origin);
  return true;
}

/**
 * Executes the **file**: saves first, then `app.run_recipe(path)`.
 *
 * A fresh namespace and a populated `__file__`, on the domain side — hence no state shared with
 * the prompt, which is exactly the opposite of `runInConsole`. It is the classic gesture (F9
 * runs the saved file), and the only one whose announced Python echo matches what actually
 * happens.
 */
export async function runFile(id: string): Promise<boolean> {
  // A refused save stops everything: running the *file* right after refusing to write to it
  // would launch the external editor's version, not the one under our eyes.
  if (!(await saveScript(id))) return false;
  const doc = scriptById(id);
  if (!doc?.path) return false; // the user backed out of the save dialog
  requestActivate('console');
  await client.call('app.run_recipe', { path: doc.path });
  return true;
}

/**
 * The code a "Run selection" must send.
 *
 * Empty selection → the cursor line, the VS Code convention: the gesture stays useful without
 * having to select anything. Stripping the common indentation is indispensable — running a line
 * taken from a function body as-is would raise an `IndentationError` before it was even
 * evaluated.
 */
export function runnableSelection(text: string, selected: string, lineNumber: number): string {
  const chosen = selected.trim() ? selected : (text.split('\n')[lineNumber - 1] ?? '');
  return dedent(chosen);
}

/**
 * Wires the script commands sent by the server. To be called once at startup.
 *
 * This is the channel through which the built-in assistant (the `open_script` MCP tool) — or
 * any agent connected to `/mcp` — drops a script in front of the user. Same philosophy as
 * `project.command`: the server decides, the client renders.
 */
export function connectScripts(): void {
  client.onNotification((method, params) => {
    if (method !== 'scripts.command') return;
    const command = params as { op: string; path?: string | null; text?: string; title?: string };
    if (command.op === 'open') {
      if (command.path) adoptScript(command.path, command.text ?? '');
      else newScript(command.text ?? '', command.title ?? '');
    }
  });
}

/** Strips the indentation common to the non-empty lines. */
export function dedent(text: string): string {
  const lines = text.split('\n');
  const indents = lines
    .filter((line) => line.trim())
    .map((line) => line.length - line.trimStart().length);
  const common = indents.length ? Math.min(...indents) : 0;
  if (common === 0) return text;
  return lines.map((line) => (line.trim() ? line.slice(common) : line)).join('\n');
}
