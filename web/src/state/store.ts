// Client-side mirror of the server state.
//
// The server rebroadcasts a complete snapshot on every burst of mutations: the store therefore
// has no merge logic, it replaces. The whole UI derives from `snapshot` through computed
// signals — that is what makes the rendering declarative without a client-side state machine.
//
// Two streams escape the snapshot because they are too frequent:
//   - `viewport.changed`: updated in place in the window concerned;
//   - `echo`: relayed verbatim to the subscribers (the console transcript), not stored here.

import { batch, computed, signal } from '@preact/signals';

import { client, type ConnectionState } from '../api/client';
import { imageFormats } from '../api/formats';
import { hydrateNotifications, pushToast } from '../notifications/store';
import { adoptSession, showHomeIfEmpty } from '../project/project';
import { adoptLayout } from '../shell/layoutClient';
import { reconcileWithServer } from '../shell/locale';
import type {
  EchoEvent,
  Hello,
  ProcessMeta,
  Snapshot,
  ViewportChanged,
  ViewState,
  WindowState,
} from '../api/types';

export const connection = signal<ConnectionState>('connecting');
export const snapshot = signal<Snapshot | null>(null);
/** RPC methods announced by the server — useful for introspection and the palette. */
export const methods = signal<readonly string[]>([]);
/** Process catalog — loaded once, it does not change during a session. */
export const processes = signal<readonly ProcessMeta[]>([]);

/** Processes grouped by category, sorted — the shape the explorer expects. */
export const processesByCategory = computed(() => {
  const groups = new Map<string, ProcessMeta[]>();
  for (const process of processes.value) {
    const bucket = groups.get(process.category);
    if (bucket) bucket.push(process);
    else groups.set(process.category, [process]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([category, items]) => ({
      category,
      items: [...items].sort((a, b) => a.process_id.localeCompare(b.process_id)),
    }));
});

export const windows = computed(() => snapshot.value?.windows ?? []);

export const activeWindow = computed(() => {
  const snap = snapshot.value;
  if (!snap?.active_window) return null;
  return snap.windows.find((w) => w.id === snap.active_window) ?? null;
});

export const activeView = computed(() => {
  const snap = snapshot.value;
  const win = activeWindow.value;
  if (!snap?.active_view || !win) return null;
  return win.views.find((v) => v.id === snap.active_view) ?? null;
});

/** Finds a view (main or preview) and its window by id — addressing is global. */
export function viewById(id: string): { view: ViewState; win: WindowState } | null {
  const snap = snapshot.value;
  if (!snap) return null;
  for (const win of snap.windows) {
    const view = win.views.find((v) => v.id === id);
    if (view) return { view, win };
  }
  return null;
}

/**
 * True if the screen stretch moves anything — the identity is (0, 0.5, 1) per channel.
 *
 * This is the exact question behind two gestures: whether baking the stretch would do
 * something, and whether an 8-bit export is about to produce a file darker than the screen.
 * Both used to guess it separately.
 */
export function stfIsVisible(view: ViewState | null | undefined): boolean {
  if (!view?.stf.enabled) return false;
  return view.stf.channels.some(
    (c) => c.shadows !== 0 || c.midtones !== 0.5 || c.highlights !== 1,
  );
}

/**
 * Subscribers to the Python echo of the interface actions.
 *
 * The echo is **not** stored here. It used to be, in a bounded buffer that two views rendered
 * identically — the console and a "Log" panel since removed. Since the console transcript is
 * already a store (bounded, serialized into projects), keeping a second copy served only to
 * make them diverge.
 *
 * A subscriber registered at startup receives everything: `connectTranscript()` registers
 * before the WebSocket opens, so no echo precedes the first listener.
 */
const echoListeners = new Set<(code: string) => void>();

export function onEcho(listener: (code: string) => void): () => void {
  echoListeners.add(listener);
  return () => echoListeners.delete(listener);
}

/** Dispatches an echo to its subscribers. Called when the `echo` notification arrives. */
export function emitEcho(code: string): void {
  for (const listener of echoListeners) listener(code);
}

function applyViewportChange(event: ViewportChanged): void {
  // The author of the gesture has already moved their camera locally: reapplying would make the
  // rendering stutter. A change coming from the console (origin null) or another client counts.
  if (event.origin === client.connectionId) return;

  const snap = snapshot.value;
  if (!snap) return;
  const index = snap.windows.findIndex((w) => w.id === event.window);
  if (index < 0) return;
  const windowsCopy = [...snap.windows];
  const target = windowsCopy[index];
  if (!target) return;
  windowsCopy[index] = { ...target, viewport: event.viewport };
  snapshot.value = { ...snap, windows: windowsCopy };
}

/** Wires the store to the RPC client. To be called once at startup. */
export function connectStore(): void {
  client.onStateChange(async (state) => {
    connection.value = state;
    if (state !== 'open') return;
    try {
      const hello = await client.call<Hello>('hello');
      client.connectionId = hello.connection;
      // Before any pixel loading: this is what prevents falling back on a previous session's
      // disk cache (see RetinaClient.scoped).
      client.run = hello.run;
      // The server is the authority on the language: it is the one translating parameter
      // labels, preprocessing notes and the documentation. If startup guessed something else,
      // reload — and stop here, the page is about to disappear.
      if (reconcileWithServer(hello.session?.effective_language)) return;
      adoptLayout(hello.layout);
      adoptSession(hello.session);
      batch(() => {
        snapshot.value = hello.snapshot;
        methods.value = hello.methods;
        // The file dialogs and the 8-bit export warning read this: the domain owns the list
        // of formats, the interface only groups them into named filters.
        if (hello.formats) imageFormats.value = hello.formats;
        // The hello is not a `state.changed` notification: the center is hydrated here.
        hydrateNotifications(hello.snapshot.notifications ?? []);
      });
      // After the first snapshot: the home screen is decided on what is open, so that has to
      // be known.
      showHomeIfEmpty(hello.snapshot.windows.length);
      // A single request at startup; if a process is born during the session, the server says
      // so (`process.changed`, below) and the catalog is read again.
      if (processes.value.length === 0) {
        processes.value = await client.call<ProcessMeta[]>('process.list');
      }
    } catch (error) {
      // An error specific to THIS client (a failed handshake): a local toast, not the center —
      // the center is shared by all clients, and this one's failure does not concern them.
      pushToast('error', error instanceof Error ? error.message : String(error));
    }
  });

  client.onNotification((method, params) => {
    switch (method) {
      case 'state.changed':
        snapshot.value = params as Snapshot;
        break;
      case 'viewport.changed':
        applyViewportChange(params as ViewportChanged);
        break;
      case 'echo':
        emitEcho((params as EchoEvent).code);
        break;
      case 'process.changed':
        // A process was born during the session (console, assistant, user directory):
        // the "requested once" catalog is read again here, and nowhere else — this is
        // the only exception, and it is driven by the server.
        void client
          .call<ProcessMeta[]>('process.list')
          .then((list) => {
            processes.value = list;
          })
          .catch(() => undefined);
        break;
      default:
        console.warn('unhandled notification', method, params);
    }
  });

  client.connect();
}
