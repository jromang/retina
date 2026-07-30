// Client-side notifications: mirror of the domain center + local ephemeral toasts.
//
// Two levels, and the distinction is architectural:
//   - the **center** (`notifications`) is domain state (`app.notifications`), shared by all
//     clients and replayed by the snapshot — it is what the bell unfolds;
//   - the **toasts** are local to this client: an RPC error (rejected form, unreachable
//     server) belongs to it alone — pushing it into the center would broadcast it to everyone.
// A domain notification *also* produces a toast: the center is the memory, the toast is the
// announcement.

import { computed, signal } from '@preact/signals';

import { client } from '../api/client';
import type { NotificationState, Snapshot } from '../api/types';

export type NotificationKind = NotificationState['kind'];
export type ServerNotification = NotificationState;

export interface Toast {
  key: string;
  kind: NotificationKind;
  message: string;
  source?: string | undefined;
  /** An error toast only leaves on a gesture: missing it would mean missing the failure. */
  sticky: boolean;
}

/** Lifetime of a non-persistent toast. */
const TOAST_MS = 6000;

/** Mirror of the domain center, most recent first (the server's order is authoritative). */
export const notifications = signal<readonly ServerNotification[]>([]);
export const toasts = signal<readonly Toast[]>([]);
export const centerOpen = signal(false);

export const errorCount = computed(
  () => notifications.value.filter((n) => n.kind === 'error').length,
);

let toastCounter = 0;

/** Shows a local toast. Info/warning fade by themselves; an error waits to be dismissed. */
export function pushToast(kind: NotificationKind, message: string, source?: string): void {
  const key = `t${++toastCounter}`;
  const toast: Toast = { key, kind, message, source, sticky: kind === 'error' };
  toasts.value = [...toasts.value, toast];
  if (!toast.sticky) setTimeout(() => dismissToast(key), TOAST_MS);
}

export function dismissToast(key: string): void {
  toasts.value = toasts.value.filter((t) => t.key !== key);
}

/** Removes an entry from the center — a domain gesture, hence RPC (and a Python echo). */
export function dismiss(id: string): void {
  void client.call('notifications.dismiss', { id }).catch((e: unknown) => console.error(e));
}

export function clearAll(): void {
  void client.call('notifications.clear').catch((e: unknown) => console.error(e));
}

/**
 * Realigns the mirror on the server's list.
 *
 * Pure replacement: the server is the authority (the center can also be manipulated from the
 * console). The same notification may arrive twice — the `hello` snapshot then the replay of
 * pending notifications — which has no effect here, the list already carries the final state.
 */
export function hydrateNotifications(list: readonly ServerNotification[]): void {
  notifications.value = list;
}

function added(note: ServerNotification): void {
  // Upsert by id: the `notification.added` notification can double a snapshot that already
  // carried the entry (hello burst + replay). A blind append would duplicate the row.
  if (notifications.value.some((n) => n.id === note.id)) return;
  notifications.value = [note, ...notifications.value];
  pushToast(note.kind, note.message, note.source || undefined);
}

/** Wires the module to the RPC client. Call once at startup, before `connectStore`. */
export function connectNotifications(): void {
  client.onNotification((method, params) => {
    switch (method) {
      case 'state.changed':
        hydrateNotifications((params as Snapshot).notifications ?? []);
        break;
      case 'notification.added':
        added(params as ServerNotification);
        break;
      case 'notification.dismissed': {
        const { id } = params as { id: string };
        notifications.value = notifications.value.filter((n) => n.id !== id);
        break;
      }
      case 'notification.cleared':
        notifications.value = [];
        break;
      default:
        break;
    }
  });
}
