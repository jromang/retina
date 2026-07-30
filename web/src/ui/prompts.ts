// Modal input and confirmation — replacements for `globalThis.prompt`/`confirm`.
//
// # Why not keep the browser dialogs
//
// Three reasons, in order of severity. They **block the event loop**: while a `prompt()` is
// open, the viewport does not redraw and notifications pile up. They render light gray system
// chrome in the middle of a dark shell, with the host name as the title ("127.0.0.1:8765
// says"). And above all they are not guaranteed in an embedded WebView, where nothing compels
// the host to implement them.
//
// The API remains a promise, like the native dialogs of `shell/native.ts`: the caller `await`s,
// without knowing who renders the box.

import { m } from '../paraglide/messages';

import { signal } from '@preact/signals';

export interface PromptChoice {
  value: string;
  label: string;
}

export interface PromptRequest {
  kind: 'text' | 'confirm' | 'choice';
  title: string;
  initial: string;
  confirmLabel: string;
  /** `choice` only: the options offered, in display order. */
  choices?: readonly PromptChoice[];
  resolve: (value: string | null) => void;
}

/** Request in progress. One at a time — a stack of modals would help nobody. */
export const promptRequest = signal<PromptRequest | null>(null);

function ask(request: Omit<PromptRequest, 'resolve'>): Promise<string | null> {
  return new Promise((resolve) => {
    const previous = promptRequest.value;
    // A modal already open is cancelled rather than stacked: its promise must settle,
    // otherwise the caller would wait forever.
    if (previous) previous.resolve(null);
    promptRequest.value = {
      ...request,
      resolve: (value) => {
        promptRequest.value = null;
        resolve(value);
      },
    };
  });
}

/** Returns the entered text, or `null` if the user backs out. */
export function promptText(
  title: string,
  initial = '',
  // A **lazy** default: evaluated at call time, hence in the current language. A literal placed
  // here would have been frozen at module import, before the language was even resolved.
  confirmLabel: string = m.prompt_ok(),
): Promise<string | null> {
  return ask({ kind: 'text', title, initial, confirmLabel });
}

/**
 * Returns the value chosen from a list, or `null` if the user backs out.
 *
 * Designating an existing view — mask, registration reference — is a recurring gesture, and
 * making it typed by hand invited typos on an identifier the domain rejects. An empty list
 * returns `null` without displaying anything: offering a modal with no option would be a dead
 * end.
 */
export async function promptChoice(
  title: string,
  choices: readonly PromptChoice[],
  confirmLabel: string = m.prompt_ok(),
): Promise<string | null> {
  if (choices.length === 0) return null;
  return ask({
    kind: 'choice',
    title,
    initial: choices[0]!.value,
    confirmLabel,
    choices,
  });
}

/** Returns `true` if the user confirms. */
export async function confirmBox(
  message: string,
  confirmLabel: string = m.prompt_confirm(),
): Promise<boolean> {
  return (await ask({ kind: 'confirm', title: message, initial: '', confirmLabel })) !== null;
}
