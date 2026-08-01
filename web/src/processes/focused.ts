// Which process form the user is working in.
//
// F1 is announced — by the guided tour and by the form's own tooltip — as "the documentation of
// the selected process". Until now it opened the index, because the shortcut is derived from the
// panel registry (`panel.doc`) and a panel command knows nothing about what is open beside it.
//
// The missing piece is small: the *last form touched*. Several tool windows can be stacked in
// the right zone, so "the open one" is not a question with an answer; "the one just clicked in"
// is. A pointer down on the form records it, closing it forgets it — no focus tracking, which
// would fight the fields' own focus handling.

import { signal } from '@preact/signals';

export const focusedProcess = signal<string | null>(null);

export function noteProcessFocus(processId: string): void {
  focusedProcess.value = processId;
}

export function forgetProcessFocus(processId: string): void {
  if (focusedProcess.value === processId) focusedProcess.value = null;
}

/** How many recently-used processes the explorer shows. Enough to cover a working session. */
const RECENT_MAX = 6;

/**
 * Processes applied during this session, most recent first.
 *
 * A session uses a dozen of the 141, over and over, and finding each of them again meant
 * scrolling a category or retyping a search. Kept in memory only, deliberately: persisting it
 * would make the panel's top rows depend on what one did last week, and the list is worth
 * nothing without the images it went with.
 */
export const recentProcesses = signal<readonly string[]>([]);

export function noteProcessUsed(processId: string): void {
  const rest = recentProcesses.value.filter((id) => id !== processId);
  recentProcesses.value = [processId, ...rest].slice(0, RECENT_MAX);
}
