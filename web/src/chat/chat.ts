// State of the assistant panel — the testable half, without a DOM (`console/transcript.ts`
// pattern).
//
// The server sends **structured** data (`chat.event`, typed by `type`); this is where the
// streamed prose is merged into bubbles and tool calls become readable lines. Conversation
// content is not translated; the chrome (tool labels, states) is composed on the client with
// paraglide — the only split compatible with the i18n rule.

import { signal } from '@preact/signals';

import { client } from '../api/client';
import { m } from '../paraglide/messages';

export interface ChatBlock {
  id: number;
  kind: 'user' | 'text' | 'tool_call' | 'tool_result' | 'turn_done' | 'error';
  text: string;
  tool?: string | undefined;
  args?: Record<string, unknown> | undefined;
  ok?: boolean | undefined;
  turn: number;
}

export interface ChatStatus {
  installed: boolean;
  version: string | null;
  authenticated: boolean | null;
  subscription: string | null;
  busy: boolean;
  mcp_available: boolean;
  session: string | null;
  ready: boolean;
  version_supported: boolean;
  version_untested: boolean;
  min_version: string;
}

export const chatBlocks = signal<readonly ChatBlock[]>([]);
export const chatStatus = signal<ChatStatus | null>(null);
export const chatBusy = signal(false);

let nextId = 1;
const MAX_BLOCKS = 400;

function push(block: Omit<ChatBlock, 'id'>): void {
  const blocks = [...chatBlocks.value, { ...block, id: nextId++ }];
  chatBlocks.value = blocks.slice(-MAX_BLOCKS);
}

/** Merges streamed prose with the previous bubble of the same turn (appendStream pattern). */
function appendText(text: string, turn: number): void {
  const blocks = chatBlocks.value;
  const last = blocks.at(-1);
  if (last && last.kind === 'text' && last.turn === turn) {
    chatBlocks.value = [...blocks.slice(0, -1), { ...last, text: last.text + text }];
    return;
  }
  push({ kind: 'text', text, turn });
}

/** Label of a tool call — the chrome is translated, the content is not. */
export function toolLabel(tool: string, args: Record<string, unknown> | undefined): string {
  const arg = (name: string): string => String(args?.[name] ?? '');
  switch (tool) {
    case 'apply_process':
    case 'describe_process':
    case 'open_documentation':
      return `${m.chat_tool_generic({ tool })} — ${arg('process_id')}`;
    case 'execute_python':
      return m.chat_tool_generic({ tool: 'Python' });
    default:
      return m.chat_tool_generic({ tool });
  }
}

/**
 * Message for a failure the server was able to name.
 *
 * `unparsed_stream` is the case that matters: the CLI spoke and our parser recognized nothing.
 * That is the signature of a format that changed, and the user cannot guess it — hence a
 * sentence that says what to do rather than a bare "error".
 */
export function failureText(reason: string): string {
  switch (reason) {
    case 'unparsed_stream':
      return m.chat_error_unparsed();
    case 'no_output':
      return m.chat_error_no_output();
    case 'not_installed':
      return m.chat_error_not_installed();
    default:
      return m.chat_error({ error: reason });
  }
}

export interface ChatEvent {
  type: string;
  turn?: number;
  text?: string;
  tool?: string;
  args?: Record<string, unknown>;
  ok?: boolean;
  summary?: string;
  status?: string;
  error?: string;
  /** Machine code of a named failure — see `failureText`. */
  reason?: string;
  [key: string]: unknown;
}

export function applyEvent(event: ChatEvent): void {
  const turn = event.turn ?? 0;
  switch (event.type) {
    case 'turn_started':
      chatBusy.value = true;
      break;
    case 'text_delta':
      appendText(event.text ?? '', turn);
      break;
    case 'tool_call':
      push({ kind: 'tool_call', text: '', tool: event.tool, args: event.args, turn });
      break;
    case 'tool_result':
      push({ kind: 'tool_result', text: event.summary ?? '', ok: event.ok, turn });
      break;
    case 'turn_done':
      chatBusy.value = false;
      if (event.status === 'interrupted') {
        push({ kind: 'turn_done', text: m.chat_interrupted(), turn });
      } else if (event.status === 'error') {
        // A `reason` is a machine code the server leaves us to name; without it, the message
        // comes from the CLI and is carried verbatim.
        const text = event.reason
          ? failureText(event.reason)
          : event.error
            ? m.chat_error({ error: event.error })
            : null;
        if (text) push({ kind: 'error', text, turn });
      }
      // `auth_error` pushes no block: the `status` event that follows switches the panel to
      // the login screen, which explains better than a red line.
      void refreshChatStatus(false);
      break;
    case 'status':
      chatStatus.value = event as unknown as ChatStatus;
      break;
    case 'cleared':
      chatBlocks.value = [];
      break;
    default:
      break; // future types: ignored, as on the server side
  }
}

/** Sends a message; the blocks arrive through notifications. */
export async function sendChat(text: string): Promise<boolean> {
  const trimmed = text.trim();
  if (!trimmed || chatBusy.value) return false;
  push({ kind: 'user', text: trimmed, turn: 0 });
  chatBusy.value = true;
  try {
    await client.call('chat.send', { text: trimmed });
    return true;
  } catch (error) {
    chatBusy.value = false;
    push({
      kind: 'error',
      text: m.chat_error({ error: error instanceof Error ? error.message : String(error) }),
      turn: 0,
    });
    return false;
  }
}

export async function interruptChat(): Promise<void> {
  await client.call('chat.interrupt', {});
}

export async function newConversation(): Promise<void> {
  await client.call('chat.new', {});
}

export async function refreshChatStatus(refresh = true): Promise<void> {
  try {
    chatStatus.value = await client.call<ChatStatus>('chat.status', { refresh });
  } catch {
    // server unreachable: the client's connection state already covers this case
  }
}

/** Reloads the server transcript — rehydration on (re)connection. */
async function hydrate(): Promise<void> {
  try {
    const blocks = await client.call<Omit<ChatBlock, 'id'>[]>('chat.transcript', {});
    chatBlocks.value = blocks.map((block) => ({ ...block, id: nextId++ }));
  } catch {
    // no transcript: an empty panel is a valid state
  }
}

/** Wires the panel to the RPC client. To be called once at startup. */
export function connectChat(): void {
  client.onNotification((method, params) => {
    if (method === 'chat.event') applyEvent(params as ChatEvent);
  });
  client.onStateChange((state) => {
    if (state === 'open') {
      void hydrate();
      void refreshChatStatus(false);
    }
  });
}
