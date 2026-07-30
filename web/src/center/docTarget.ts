// Navigation target of the Documentation tab.
//
// `DocTab` loads the index when it mounts and then navigates through its own links: nothing,
// until now, allowed telling it "show the page of such-and-such process" from the outside. The
// assistant needs it (MCP tool `open_documentation`), and tomorrow a palette command will be
// able to use it too.
//
// Same pattern as the form seeds (`seededValues`/`takeSeed`): a signal set by the emitter,
// consumed — and reset to null — by the single reader. A signal rather than an event: if the
// tab is not mounted yet when the notification arrives, the target waits for it at mount time
// instead of getting lost.

import { signal } from '@preact/signals';

import { client } from '../api/client';

export const docTarget = signal<string | null>(null);

/** Consume the current target (once only). */
export function takeDocTarget(): string | null {
  const target = docTarget.value;
  if (target !== null) docTarget.value = null;
  return target;
}

/** Wire the documentation commands sent by the server. Once, at startup. */
export function connectDocs(): void {
  client.onNotification((method, params) => {
    if (method !== 'docs.command') return;
    const command = params as { op: string; process_id?: string };
    if (command.op === 'open' && command.process_id) {
      docTarget.value = command.process_id;
    }
  });
}
