// Bridge to the chrome of the native window.
//
// The window is created **without decorations** (see crates/retina_shell/src/main.rs): moving,
// maximizing, resizing and closing therefore become IPC commands. This is window chrome,
// not domain: these calls deliberately have no `app.*` equivalent and
// produce no Python echo — see the header of `menus.ts`.
//
// In browser mode (`python -m retina.web --no-shell`), everything here is inert: `invoke` returns
// `null` and the caller does not mount the buttons.

import { signal } from '@preact/signals';

import { inNativeShell } from '../native';

/** Resize direction, as expected by the shell (`parse_dir` on the Rust side). */
export type ResizeDir = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';

export const windowMaximized = signal(false);
export const windowFocused = signal(true);

async function invoke<T>(cmd: string, args: Record<string, unknown> = {}): Promise<T | null> {
  if (!inNativeShell()) return null;
  try {
    return (await window.retinaShell!.invoke(cmd, args)) as T;
  } catch (error) {
    console.error('window command', cmd, error);
    return null;
  }
}

export function windowDrag(): void {
  void invoke('window_drag');
}

export function windowStartResize(direction: ResizeDir): void {
  void invoke('window_resize', { direction });
}

export function windowMinimize(): void {
  void invoke('window_minimize');
}

export function windowToggleMaximize(): void {
  void invoke<boolean>('window_toggle_maximize').then((maximized) => {
    if (maximized !== null) windowMaximized.value = maximized;
  });
}

export function windowClose(): void {
  void invoke('window_close');
}

interface WindowStateDetail {
  maximized?: boolean;
  focused?: boolean;
}

/**
 * Listens to the state changes pushed by the shell.
 *
 * The initial read is not redundant: a `Resized` may have happened before the page was
 * loaded (window restored maximized), and the icon would then show the wrong glyph.
 */
export function connectWindow(): void {
  if (!inNativeShell()) return;

  window.addEventListener('retina-shell-window-state', (event) => {
    const detail = (event as CustomEvent<WindowStateDetail>).detail ?? {};
    if (typeof detail.maximized === 'boolean') windowMaximized.value = detail.maximized;
    if (typeof detail.focused === 'boolean') windowFocused.value = detail.focused;
  });

  void invoke<boolean>('window_is_maximized').then((maximized) => {
    if (maximized !== null) windowMaximized.value = maximized;
  });
}
