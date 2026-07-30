// Client-side real-time preview — one preview per form, and debouncing.
//
// The debounce lives **here** and not on the server: it is the client that knows when the
// user has finished moving a slider. The server, for its part, holds the generation counter
// and discards stale results (cf. server/rtp.py) — both halves are necessary.
//
// [RETHOUGHT] A single form drove the preview, and ticking "Preview" on a second one evicted
// the first **without saying so**. Yet the question one asks in front of two settings is
// precisely "which of the two": each form therefore has its preview, and its panel. The
// debounce stays per owner — moving a slider must not restart the neighbour's computation.

import { computed, signal } from '@preact/signals';

import { client } from '../api/client';

/** Same value as the Qt shell's `_DEBOUNCE_MS`: below 250 ms we restart for nothing. */
const DEBOUNCE_MS = 250;

export interface RtpFrame {
  generation: number;
  owner: string | null;
  /** View (main or preview) this preview was computed on — the panel renders the curtain and
   *  the STF from it, never from the active view, which may have changed since. */
  view: string;
  width: number;
  height: number;
  channels: number;
  seconds: number;
}

/** Processes driving a preview, in the order in which they asked for it. */
export const rtpOwners = signal<string[]>([]);
/** Last frame of each owner. */
export const rtpFrames = signal<Record<string, RtpFrame>>({});
export const rtpErrors = signal<Record<string, string>>({});
export const rtpActive = computed(() => rtpOwners.value.length > 0);

/** True if this process drives a preview — what the form's checkbox ticks. */
export function ownsRtp(processId: string): boolean {
  return rtpOwners.value.includes(processId);
}

interface Pending {
  params: Record<string, unknown>;
  view: string;
}

const timers = new Map<string, number>();
const pending = new Map<string, Pending>();

function send(processId: string): void {
  const attente = pending.get(processId);
  if (!attente) return;
  pending.delete(processId);
  void client
    .call('rtp.request', {
      process_id: processId,
      params: attente.params,
      view: attente.view,
      owner: processId,
    })
    .catch((error: unknown) => {
      rtpErrors.value = {
        ...rtpErrors.value,
        [processId]: error instanceof Error ? error.message : String(error),
      };
    });
}

function forget(processId: string): void {
  const { [processId]: _frame, ...frames } = rtpFrames.value;
  const { [processId]: _error, ...errors } = rtpErrors.value;
  rtpFrames.value = frames;
  rtpErrors.value = errors;
  rtpOwners.value = rtpOwners.value.filter((id) => id !== processId);
  globalThis.clearTimeout(timers.get(processId));
  timers.delete(processId);
  pending.delete(processId);
}

/** Open a preview for this process. Idempotent: re-ticking does not duplicate it. */
export function acquireRtp(processId: string): void {
  if (!rtpOwners.value.includes(processId)) {
    rtpOwners.value = [...rtpOwners.value, processId];
  }
  const { [processId]: _, ...errors } = rtpErrors.value;
  rtpErrors.value = errors;
}

export function releaseRtp(processId: string): void {
  if (!rtpOwners.value.includes(processId)) return;
  forget(processId);
  void client.call('rtp.release', { owner: processId }).catch(() => undefined);
}

/** Request a preview, debounced per owner. To be called on every parameter change. */
export function requestRtp(
  processId: string,
  params: Record<string, unknown>,
  view: string,
): void {
  if (!rtpOwners.value.includes(processId)) return;
  pending.set(processId, { params, view });
  globalThis.clearTimeout(timers.get(processId));
  timers.set(processId, globalThis.setTimeout(() => send(processId), DEBOUNCE_MS));
}

export function connectRtp(): void {
  client.onNotification((method, params) => {
    if (method === 'rtp.ready') {
      const frame = params as RtpFrame;
      const owner = frame.owner ?? '';
      rtpFrames.value = { ...rtpFrames.value, [owner]: frame };
      const { [owner]: _, ...errors } = rtpErrors.value;
      rtpErrors.value = errors;
    } else if (method === 'rtp.failed') {
      const { owner, message } = params as { owner: string | null; message: string };
      rtpErrors.value = { ...rtpErrors.value, [owner ?? '']: message };
    } else if (method === 'rtp.released') {
      // The server bounds the number of previews: when it closes one, the panel must
      // disappear rather than stay frozen on an image it will no longer receive.
      forget((params as { owner: string | null }).owner ?? '');
    }
  });
}
