// Notification store: mirror of the domain center plus local toasts.
//
// The traps covered here are the ones that were designed for: double delivery (the same
// notification arrives both in the hello snapshot AND in the replay of pending notifications —
// no duplicate), auto-clearing of info toasts versus the persistence of errors, and dismissal
// going through RPC (hence through app.notifications, hence with an echo).

import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { NotificationState } from '../src/api/types';

// `api/client` reads the token when the module loads: it needs a plausible window.
vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const { client } = await import('../src/api/client');
const {
  notifications,
  toasts,
  errorCount,
  hydrateNotifications,
  pushToast,
  dismissToast,
  dismiss,
  connectNotifications,
} = await import('../src/notifications/store');

function note(over: Partial<NotificationState> = {}): NotificationState {
  return {
    id: 'n1',
    kind: 'error',
    message: 'ValueError: nothing to integrate',
    source: 'Integration',
    timestamp: 1_753_600_000,
    ...over,
  };
}

/** Replays an RPC notification to the subscribers (connectNotifications is wired once). */
let dispatch: (method: string, params: unknown) => void = () => undefined;
const handlers: Array<(method: string, params: unknown) => void> = [];
vi.spyOn(client, 'onNotification').mockImplementation((h) => {
  handlers.push(h);
  return () => undefined;
});
connectNotifications();
dispatch = (method, params) => handlers.forEach((h) => h(method, params));

describe('notifications', () => {
  beforeEach(() => {
    notifications.value = [];
    toasts.value = [];
  });

  it('hydrates by replacing: the server is the authority', () => {
    hydrateNotifications([note()]);
    hydrateNotifications([note({ id: 'n2', kind: 'info' })]);

    expect(notifications.value.map((n) => n.id)).toEqual(['n2']);
    expect(errorCount.value).toBe(0);
  });

  it('notification.added prepends and produces a toast', () => {
    dispatch('notification.added', note());

    expect(notifications.value).toHaveLength(1);
    expect(toasts.value).toHaveLength(1);
    expect(toasts.value[0]?.sticky).toBe(true); // an error waits to be dismissed
  });

  it('does not duplicate an entry already hydrated (hello + replay)', () => {
    hydrateNotifications([note()]);
    dispatch('notification.added', note());

    expect(notifications.value).toHaveLength(1);
    expect(toasts.value).toHaveLength(0); // already known: not announced again
  });

  it('dismissed and cleared keep the mirror in step', () => {
    hydrateNotifications([note(), note({ id: 'n2' })]);
    dispatch('notification.dismissed', { id: 'n1' });
    expect(notifications.value.map((n) => n.id)).toEqual(['n2']);

    dispatch('notification.cleared', {});
    expect(notifications.value).toEqual([]);
  });

  it('an info toast clears itself, an error stays', () => {
    vi.useFakeTimers();
    try {
      pushToast('info', 'saved');
      pushToast('error', 'boom');
      expect(toasts.value).toHaveLength(2);

      vi.advanceTimersByTime(7000);
      expect(toasts.value.map((t) => t.kind)).toEqual(['error']);

      const key = toasts.value[0]?.key ?? '';
      dismissToast(key);
      expect(toasts.value).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it('dismiss goes through RPC — the gesture belongs to the domain', async () => {
    const call = vi.spyOn(client, 'call').mockResolvedValue(true);
    dismiss('n1');
    expect(call).toHaveBeenCalledWith('notifications.dismiss', { id: 'n1' });
    call.mockRestore();
  });
});
