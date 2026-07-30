// Root of the file explorer — a module signal, not a component state.
//
// # Why this value left FilesPanel's `useState`
//
// It must be settable **from the outside**: opening a project must reopen *its* working
// folder, not the last one visited. A `useState` is only reachable from the mounted
// component, and the panel may very well not be mounted at restoration time.
//
// `localStorage` remains the fallback outside a project: the root is a shell preference, like
// the width of the zones. What changes is that a project can now override it.

import { signal } from '@preact/signals';

const ROOT_KEY = 'retina.files.root';

function initial(): string | null {
  try {
    return localStorage.getItem(ROOT_KEY);
  } catch {
    // A browser in private mode can refuse access: that is no reason not to start, the
    // server will return its home folder.
    return null;
  }
}

/** `null` → the server answers with *its* home folder. */
export const filesRoot = signal<string | null>(initial());

export function setFilesRoot(path: string | null): void {
  filesRoot.value = path;
  try {
    if (path === null) localStorage.removeItem(ROOT_KEY);
    else localStorage.setItem(ROOT_KEY, path);
  } catch {
    // same thing: the preference will not survive a reload, the application will.
  }
}
