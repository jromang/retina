// Client-side tracking of process runs.
//
// The server returns a job id immediately then tells the rest of the story by notifications.
// This module holds their state, so that a form's progress bar and the status bar talk about
// the same thing.

import { computed, signal } from '@preact/signals';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import type { JobSnapshot, Snapshot } from '../api/types';
import { pushToast } from '../notifications/store';
import { processes } from '../state/store';

export interface JobState {
  id: string;
  process_id: string;
  view: string | null;
  state: 'queued' | 'running' | 'done' | 'error' | 'cancelled';
  /** `null` = indeterminate progress: the process does not instrument its loops.
   *  Long processes (integration, measurements, registration, denoising) do fill it in. */
  fraction: number | null;
  message: string;
  /** Output of a measurement process — cf. `JobSnapshot.result`. */
  result?: Record<string, unknown> | null;
  /** Windows this run opened. Fifteen processes create one instead of transforming a view. */
  created_windows?: string[];
}

export const jobs = signal<Readonly<Record<string, JobState>>>({});

export const activeJobs = computed(() =>
  Object.values(jobs.value).filter((job) => job.state === 'queued' || job.state === 'running'),
);

/** Job in flight for a given process — what its progress bar must display. */
export function jobFor(processId: string): JobState | null {
  return activeJobs.value.find((job) => job.process_id === processId) ?? null;
}

/**
 * Last **finished** job of a process, as long as it has not been forgotten.
 *
 * This is how a measurement panel collects its result: the job disappears one second after it
 * ends (`forget`), which leaves the panel time to read `result` and memorise it — but not to
 * find it again later, hence the memorisation.
 */
export function lastFinished(processId: string): JobState | null {
  return (
    Object.values(jobs.value).find(
      (job) => job.process_id === processId && job.state === 'done',
    ) ?? null
  );
}

function upsert(id: string, patch: Partial<JobState> & { process_id?: string }): void {
  const current = jobs.value[id];
  const next: JobState = {
    id,
    process_id: patch.process_id ?? current?.process_id ?? '',
    view: patch.view ?? current?.view ?? null,
    state: patch.state ?? current?.state ?? 'queued',
    fraction: patch.fraction ?? current?.fraction ?? null,
    message: patch.message ?? current?.message ?? '',
    result: patch.result ?? current?.result ?? null,
    created_windows: patch.created_windows ?? current?.created_windows ?? [],
  };
  jobs.value = { ...jobs.value, [id]: next };
}

function forget(id: string): void {
  // Finished jobs stay for a second: the bar has time to show its final state before
  // disappearing, otherwise a fast process just flickers without saying anything.
  setTimeout(() => {
    const { [id]: _removed, ...rest } = jobs.value;
    jobs.value = rest;
  }, 1000);
}

export async function runProcess(
  processId: string,
  params: Record<string, unknown>,
  view?: string,
): Promise<string> {
  const payload: Record<string, unknown> = { process_id: processId, params };
  if (view) payload['view'] = view;
  const result = await client.call<{ job: string }>('process.run', payload);
  upsert(result.job, { process_id: processId, state: 'queued' });
  return result.job;
}

/**
 * Run a whole recipe — a single job, in order.
 *
 * Looping `runProcess` over the steps would launch N concurrent jobs on a pool of four
 * threads: the order would not be guaranteed, and the order *is* the meaning of a pipeline.
 */
export async function runContainer(
  processes: readonly { process_id: string; values: Record<string, unknown> }[],
  view?: string,
  name?: string,
): Promise<string> {
  const payload: Record<string, unknown> = { processes };
  if (view) payload['view'] = view;
  if (name) payload['name'] = name;
  const result = await client.call<{ job: string }>('process.run_container', payload);
  upsert(result.job, { process_id: name ?? m.process_recipe(), state: 'queued' });
  return result.job;
}

/**
 * Wait for a job to finish, and hand back its result.
 *
 * For a caller that has work to chain on the outcome — the sample download, which opens the
 * wizard on the folder it just filled. Resolves to `null` on cancellation or error: both are
 * already reported (notification centre, error toast), and the caller's job is to *not*
 * continue, not to report them a second time.
 */
export function awaitJob(id: string): Promise<Record<string, unknown> | null> {
  return new Promise((resolve) => {
    const stop = client.onNotification((method, params) => {
      const data = params as { job?: string; id?: string; result?: Record<string, unknown> };
      if ((data.job ?? data.id) !== id) return;
      if (method === 'job.done') {
        stop();
        resolve(data.result ?? null);
      } else if (method === 'job.error' || method === 'job.cancelled') {
        stop();
        resolve(null);
      }
    });
  });
}

export function cancelJob(id: string): void {
  void client.call('process.cancel', { job: id }).catch((e: unknown) => console.error(e));
}

/** Realign the job state on the server snapshot.
 *
 *  The server only publishes the jobs **in flight**: its list is therefore authoritative for
 *  those, and only for those. Finished jobs, known through notifications, are kept for as
 *  long as their bar shows its final state — a snapshot no longer mentions them, but that
 *  does not mean they never existed.
 *
 *  A job launched just now may be missing from a snapshot already in flight: the `job.started`
 *  notification that follows recreates it with all its metadata. */
export function hydrateJobs(active: readonly JobSnapshot[]): void {
  const next: Record<string, JobState> = {};
  for (const job of active) {
    next[job.id] = {
      id: job.id,
      process_id: job.process_id,
      view: job.view,
      state: job.state,
      fraction: job.fraction,
      // a job in flight has no error message: what matters is which stage it is at
      message: job.progress_message || job.message,
    };
  }
  for (const [id, job] of Object.entries(jobs.value)) {
    if (job.state !== 'queued' && job.state !== 'running') next[id] = job;
  }
  jobs.value = next;
}

/**
 * Say that a window was opened, and offer what to do with it.
 *
 * A process that creates a window did so in silence: `StarMask` produced `Image01_StarMask`
 * somewhere in the Windows panel, and nothing connected it to the gesture it exists for —
 * setting it as the mask of the view it was computed from, which lives three menus away under
 * View ▸ Mask ▸ Set mask from a view. The toast is a shortcut, not a new capability: the menu
 * entry and `app.set_mask` are unchanged, and the button calls the latter.
 *
 * The offer is confined to `MaskGeneration`, the only family whose output is *made* to become
 * a mask. `AberrationInspector`'s mosaic and `NewImage`'s canvas get the plain announcement.
 */
function announceCreatedWindows(job: JobState | undefined): void {
  const created = job?.created_windows?.[0];
  if (!job || !created) return;
  const meta = processes.value.find((p) => p.process_id === job.process_id);
  const isMask = meta?.category === 'MaskGeneration';
  // `job.view` is the view the process ran on; `app.set_mask` addresses a window, and the
  // domain resolves the id either way.
  const target = job.view;
  if (!isMask || !target) {
    pushToast('info', m.status_window_created({ window: created }), job.process_id);
    return;
  }
  pushToast('info', m.status_mask_created({ window: created }), job.process_id, {
    label: m.status_mask_use({ view: target }),
    run: () => {
      void client
        .call('app.set_mask', { source: created, window: target })
        .catch((e: unknown) => console.error(e));
    },
  });
}

export function connectJobs(): void {
  client.onNotification((method, params) => {
    // The snapshot carries the jobs in flight: it is what repairs the state after a
    // reconnection, where notifications alone would leave a ghost bar.
    if (method === 'state.changed') {
      hydrateJobs((params as Snapshot).jobs ?? []);
      return;
    }
    if (!method.startsWith('job.')) return;
    const data = params as Partial<JobState> & { job?: string; id?: string };
    const id = data.job ?? data.id;
    if (!id) return;

    switch (method) {
      case 'job.progress':
        upsert(id, { fraction: data.fraction ?? null, message: data.message ?? '' });
        break;
      case 'job.started':
        upsert(id, { ...data, state: 'running' });
        break;
      case 'job.done':
        upsert(id, { ...data, state: 'done' });
        announceCreatedWindows(jobs.value[id]);
        forget(id);
        break;
      case 'job.error':
      case 'job.cancelled':
        upsert(id, { ...data, state: method.slice(4) as JobState['state'] });
        forget(id);
        break;
      default:
        break;
    }
  });
}
