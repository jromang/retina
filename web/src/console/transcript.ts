// State of the console transcript.
//
// The transcript is not a terminal: it is a **document**, made of typed blocks. That is what
// makes it possible to collapse a traceback, to make an echo line clickable, and to keep a
// clean selection — three things an xterm.js could not do.

import { signal } from '@preact/signals';

import { client } from '../api/client';
import { onEcho } from '../state/store';

export type BlockKind = 'input' | 'stdout' | 'stderr' | 'result' | 'echo' | 'error';

export interface Block {
  id: number;
  kind: BlockKind;
  text: string;
  /** IPython execution number, for input blocks. */
  count?: number;
}

/** Beyond this, the transcript loses its value for review and costs in rendering. */
const MAX_BLOCKS = 1200;

export const blocks = signal<readonly Block[]>([]);
export const busy = signal(false);
/** History navigable with the arrow keys — most recent last. */
export const history = signal<readonly string[]>([]);

/**
 * Where the current execution comes from, when it is not the prompt.
 *
 * `lineOffset` is 0 for a whole buffer, and L−1 for a selection starting at line L: that is
 * what makes it possible to map a traceback line number back into the editor.
 */
export interface RunOrigin {
  scriptId: string;
  lineOffset: number;
}

/**
 * Last execution failure, with the raw traceback and its origin.
 *
 * A signal rather than a transcript block: the full traceback is already displayed by
 * `console.stream`, and duplicating it would be noise. What we want from this value is the
 * ability to attach it to an editor line — see `scripts/traceback.ts`.
 */
export const lastExecutionError = signal<{
  message: string;
  traceback: string;
  origin: RunOrigin | null;
} | null>(null);

/** Error output accumulated during the current execution — the traceback to parse. */
let errorBuffer = '';
let currentOrigin: RunOrigin | null = null;

let nextId = 1;

function push(kind: BlockKind, text: string, count?: number): void {
  if (!text) return;
  const block: Block = count === undefined ? { id: nextId++, kind, text } : { id: nextId++, kind, text, count };
  const next = [...blocks.value, block];
  blocks.value = next.length > MAX_BLOCKS ? next.slice(-MAX_BLOCKS) : next;
}

/**
 * Merges with the previous block when it is of the same kind.
 *
 * Standard output arrives in pieces (one `write` per `print`, sometimes more): without this
 * merge, a loop of 200 `print` calls would produce 200 blocks instead of one paragraph.
 */
function appendStream(kind: BlockKind, text: string): void {
  // The traceback arrives through this channel (IPython writes it to stderr now that
  // `_showtraceback` is redirected, cf. `server/console.py`): accumulate it so the offending
  // line can be extracted at the end of the execution.
  if (kind === 'stderr' && busy.value) errorBuffer += text;
  const current = blocks.value;
  const last = current[current.length - 1];
  if (last && last.kind === kind) {
    blocks.value = [...current.slice(0, -1), { ...last, text: last.text + text }];
    return;
  }
  push(kind, text);
}

export function pushEcho(code: string): void {
  push('echo', code);
}

export function clearTranscript(): void {
  blocks.value = [];
}

// --- persistence (project) -------------------------------------------------

/** A block as a project carries it — without the `id`, which is reassigned on reload. */
export type SerializedBlock = Omit<Block, 'id'>;

/**
 * The last blocks, for a project.
 *
 * Bounded shorter than `MAX_BLOCKS`: the transcript has no business weighing on a project
 * file, and what one wants back after reopening is the immediate context — not twelve hundred
 * lines of stacking output. The `input` and `echo` blocks are what "New script from history"
 * reads back; the others are there to be read.
 */
export function serializeTranscript(limit = 400): SerializedBlock[] {
  return blocks.value.slice(-limit).map(({ id: _id, ...rest }) => rest);
}

export function restoreTranscript(saved: readonly SerializedBlock[]): void {
  const restored = saved.slice(-MAX_BLOCKS).map((block) => ({ ...block, id: nextId++ }));
  blocks.value = restored;
}

interface ExecuteResult {
  execution_count: number;
  status: 'ok' | 'error' | 'interrupted';
  error?: string | null;
  repr?: string | null;
}

/**
 * Executes code in the shared console.
 *
 * Returns `false` when nothing was started — empty code, or an execution already in progress.
 * The caller must tell the user: an F5 that does nothing *and* says nothing is the worst of
 * both worlds, and that was the behavior until now.
 */
export async function execute(code: string, origin: RunOrigin | null = null): Promise<boolean> {
  const trimmed = code.trim();
  if (!trimmed || busy.value) return false;

  push('input', code);
  // Two identical executions in a row make a single history entry — IPython's behavior, and
  // what keeps a `run()` repeated ten times from drowning everything else under the arrows.
  if (history.value[history.value.length - 1] !== code) history.value = [...history.value, code];
  busy.value = true;
  lastExecutionError.value = null;
  errorBuffer = '';
  currentOrigin = origin;
  try {
    const result = await client.call<ExecuteResult>('console.execute', { code });
    if (result.repr) push('result', result.repr, result.execution_count);
    if (result.status === 'interrupted') push('error', 'Interrompu.');
    // `result.error` used to be plainly ignored. We do not repeat the traceback — it is
    // already displayed by `console.stream` — but we keep it: it carries the line number,
    // while `result.error` carries the short message.
    else if (result.status === 'error' && result.error) {
      lastExecutionError.value = {
        message: result.error,
        traceback: errorBuffer,
        origin: currentOrigin,
      };
    }
  } catch (error) {
    push('error', error instanceof Error ? error.message : String(error));
  } finally {
    busy.value = false;
    currentOrigin = null;
  }
  return true;
}

export function interrupt(): void {
  void client.call('console.interrupt').catch((error: unknown) => console.error(error));
}

/** Wires the transcript to the server notifications. Called once at startup. */
export function connectTranscript(): void {
  // The interface echo is inserted into the transcript, in the order it arrives.
  //
  // At module level, and not in a panel effect: the panel used to replay the whole echo from a
  // cursor reset on every mount, so closing and reopening the console copied the entire history
  // twice. The transcript, by contrast, lives independently of its view.
  onEcho(pushEcho);

  client.onNotification((method, params) => {
    if (method === 'console.stream') {
      const { name, text } = params as { name: string; text: string };
      appendStream(name === 'stderr' ? 'stderr' : 'stdout', text);
    }
  });

  client.onStateChange((state) => {
    if (state !== 'open' || history.value.length > 0) return;
    // The IPython history is persistent: fetch it so that the arrow keys work from the very
    // first keystroke, including after a server restart.
    void client
      .call<string[]>('console.history', { limit: 200 })
      .then((entries) => {
        history.value = entries;
      })
      .catch(() => undefined);
  });
}
