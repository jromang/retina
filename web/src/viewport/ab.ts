// A/B toggle — go back to the previous view, at the same framing.
//
// Comparing two views means seeing them **in the same place**: side by side, the eye detects
// neither a noise difference nor a halo, whereas a toggle at the same framing makes them obvious.
//
// The memory of "the view we came from" lives here, and not in `ViewportPanel`, for two
// reasons. First, a palette command must be able to trigger the toggle without the viewport
// having focus — inside the panel, the shortcut only existed for whoever already knew that
// they had to click the image first. Second, the state survives unmounting the panel
// (tab switch), where a `useRef` started over from scratch.
//
// The gesture itself goes through `app.select_view`: the domain is what decides the current
// view, and the echo writes it into the console. What makes the toggle instantaneous is not
// a short circuit, it is the renderer's texture cache.

import { signal } from '@preact/signals';

import { client } from '../api/client';
import { windows } from '../state/store';

/** Last view left — the target of the toggle. */
export const previousView = signal<string>('');

/** Records the view we have just left. Called by the viewport on every change. */
export function rememberView(left: string, current: string): void {
  if (left && left !== current) previousView.value = left;
}

/**
 * View to toggle to, or an empty string if there is nothing to compare.
 *
 * The view we came from, if it still exists; otherwise the next one in the active window.
 * A preview deleted in the meantime must not block the toggle.
 */
export function abTarget(): string {
  const win = windows.value.find((w) => w.views.some((v) => v.id === w.current_view))
    ?? windows.value[0];
  if (!win || win.views.length < 2) return '';
  const current = win.current_view;
  const previous = win.views.find((v) => v.id === previousView.value);
  if (previous && previous.id !== current) return previous.id;
  const rank = win.views.findIndex((v) => v.id === current);
  return win.views[(rank + 1) % win.views.length]?.id ?? '';
}

export function toggleAB(): void {
  const target = abTarget();
  if (target) void client.call('app.select_view', { view: target }).catch(() => undefined);
}
