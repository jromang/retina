// Preprocessing wizard state — the logic, kept apart from the rendering.
//
// The wizard is a client of the API like any other: it calls `pipeline.scan`, `pipeline.plan`
// then `pipeline.run`, and has no power of its own. Everything it does is written to the console
// as replayable Python, because the echo comes from the server, not from it.
//
// This module touches neither the DOM nor Preact: it is testable as is (the project's vitest
// tests run without a browser), and this is where the decisions live — which rows to show,
// which stage of the walkthrough is reachable, where the job stands.

import { computed, signal } from '@preact/signals';

import { client } from '../api/client';
import { m } from '../paraglide/messages';
import { jobs } from '../processes/jobs';

export interface FrameInfo {
  path: string;
  kind: 'light' | 'dark' | 'flat' | 'bias' | 'unknown';
  filter: string | null;
  exposure: number | null;
  binning: number;
  temperature: number | null;
  gain: number | null;
  width: number | null;
  height: number | null;
  bayer: string | null;
  /** Where `kind` comes from: FITS header, file name, default, or manual correction. */
  source: 'header' | 'filename' | 'default' | 'user';
  /** Dropped from processing by the user — grouping ignores it. */
  excluded: boolean;
}

/** The kinds assignable by hand (`unknown` is corrected, never chosen). */
export const KINDS = ['light', 'dark', 'flat', 'bias'] as const;
export type Kind = (typeof KINDS)[number];

export interface Inventory {
  root: string;
  frames: FrameInfo[];
}

export interface PresetInfo {
  name: string;
  label: string;
  hint: string;
}

export interface PlanStepInfo {
  id: string;
  kind: 'per_frame' | 'global';
  label: string;
  group: string | null;
  inputs: string[];
  outputs: string[];
  bindings: Record<string, string>;
  processes: { process_id: string; values: Record<string, unknown> }[];
  /** Scripts run around the step; absent as long as none is attached. */
  hooks?: Record<string, string>;
}

/** A final image announced by the plan. */
export interface PlanProduct {
  key: string;
  filter: string | null;
  frames: number;
  exposure: number | null;
  path: string;
  /** Cumulative exposure in seconds, or `null` if the unit exposure is unknown. */
  integration: number | null;
}

export interface DiskUsage {
  stages: Record<string, number>;
  total_bytes: number;
  free_bytes: number | null;
}

export interface PlanInfo {
  version: string;
  root: string;
  output_dir: string;
  preset: { name: string };
  notes: string[];
  products: PlanProduct[];
  disk: DiskUsage;
  steps: PlanStepInfo[];
}

export interface RunReport {
  output_dir: string;
  results: string[];
  executed: string[];
  skipped: string[];
  reference: string | null;
  notes: string[];
  /** What each group actually yielded — cumulative exposure **after** selection.
   *  `PlanInfo.products` only gives an upper bound: it is computed before any measurement. */
  products: {
    key: string;
    frames: number;
    measured: number;
    rejected: number;
    integration: number | null;
  }[];
}

/** A group as the domain forms it — same keys as the plan's. */
export interface GroupInfo {
  key: string;
  kind: FrameInfo['kind'];
  filter: string | null;
  exposure: number | null;
  binning: number;
  temperature: number | null;
  gain: number | null;
  count: number;
  frames: FrameInfo[];
}

/** One operation of the calibration chain, as the domain describes it. */
export interface CalibrationStep {
  op: 'subtract' | 'divide';
  role: 'bias' | 'dark' | 'flat';
  master: string;
  scale: number;
  /** Key of the bias removed from the dark before scaling it — the "dark current" frame. */
  derived: string | null;
}

/** The masters selected for a group of lights (or of flats). */
export interface CalibrationMatch {
  target: string;
  bias: string | null;
  dark: string | null;
  flat: string | null;
  dark_scale: number;
  chain: CalibrationStep[];
  notes: string[];
}

export interface SurveyInfo {
  groups: GroupInfo[];
  matches: Record<string, CalibrationMatch>;
}

/** One row of the detected-groups table. */
export interface GroupRow {
  key: string;
  kind: FrameInfo['kind'];
  filter: string | null;
  exposure: number | null;
  binning: number;
  temperature: number | null;
  count: number;
  /** True if at least one frame of the group was classified from its file name. */
  guessed: boolean;
  /** Paths of the group's frames — corrections apply to those, the group being
   *  nothing but a display aggregation. */
  paths: string[];
  /** Every frame of the group is dropped. */
  excluded: boolean;
  /** Masters matched to this group, for lights and flats. `null` elsewhere:
   *  a dark or a bias is not calibrated. */
  calibration: CalibrationMatch | null;
}

// --- state ------------------------------------------------------------------------------

export const folder = signal<string>('');
export const inventory = signal<Inventory | null>(null);
/** Grouping and matching computed by the domain — see `groupRows`. */
export const survey = signal<SurveyInfo | null>(null);
export const presets = signal<PresetInfo[]>([]);
export const preset = signal<string>('auto');
export const plan = signal<PlanInfo | null>(null);
/**
 * A plan was built, then invalidated by a correction to the inventory or the preset.
 *
 * Without it the "Plan" section simply disappeared from the page when a group was reclassified
 * — the right thing to do with a plan that no longer describes anything, but done in silence,
 * so it read as the interface losing its place.
 */
export const planStale = signal(false);
export const report = signal<RunReport | null>(null);
export const busy = signal<boolean>(false);
export const error = signal<string>('');
/** Preprocessing job in flight — tracked by **id**, not by process name: two
 *  successive runs must not be confused with one another. */
export const jobId = signal<string | null>(null);

export const job = computed(() => (jobId.value ? (jobs.value[jobId.value] ?? null) : null));

export const running = computed(() => {
  const state = job.value?.state;
  return state === 'queued' || state === 'running';
});

/** The frames whose kind could not be determined — to be fixed before planning. */
export const unknownFrames = computed(
  () => inventory.value?.frames.filter((f) => f.kind === 'unknown') ?? [],
);

/**
 * The detected-groups table.
 *
 * The grouping comes from the **domain** (`pipeline.survey`), not from a local computation:
 * exposure and temperature tolerances, geometry, gain and the identity of the rig are astro
 * rules, and duplicating them here would guarantee they drift apart. The key displayed is
 * therefore the one the plan will use, which lets each row carry the calibration status that
 * comes from the very matching the run will do.
 *
 * **Wholly dropped** groups are no longer formed by the domain; we add them back here from
 * the inventory, without which they could never be brought back in.
 */
export const groupRows = computed<GroupRow[]>(() => {
  const etat = survey.value;
  if (!etat) return [];
  const devine = (f: FrameInfo) => f.source === 'filename' || f.source === 'default';
  const rows: GroupRow[] = etat.groups.map((group) => ({
    key: group.key,
    kind: group.kind,
    filter: group.filter,
    exposure: group.kind === 'light' || group.kind === 'dark' ? group.exposure : null,
    binning: group.binning,
    temperature: group.temperature,
    count: group.count,
    guessed: group.frames.some(devine),
    paths: group.frames.map((f) => f.path),
    excluded: false,
    calibration: etat.matches[group.key] ?? null,
  }));

  const ecartees = (inventory.value?.frames ?? []).filter(
    (f) => f.excluded && f.kind !== 'unknown',
  );
  for (const frame of ecartees) {
    const cle = `exclu·${frame.kind}·${frame.filter ?? ''}·${frame.exposure ?? ''}·${frame.binning}`;
    const row = rows.find((r) => r.key === cle);
    if (row) {
      row.count += 1;
      row.guessed ||= devine(frame);
      row.paths.push(frame.path);
    } else {
      rows.push({
        key: cle,
        kind: frame.kind,
        filter: frame.kind === 'light' || frame.kind === 'flat' ? frame.filter : null,
        exposure: frame.kind === 'light' || frame.kind === 'dark' ? frame.exposure : null,
        binning: frame.binning,
        temperature: frame.temperature,
        count: 1,
        guessed: devine(frame),
        paths: [frame.path],
        excluded: true,
        calibration: null,
      });
    }
  }

  const ordre = { light: 0, flat: 1, dark: 2, bias: 3, unknown: 4 };
  return rows.sort(
    (a, b) => ordre[a.kind] - ordre[b.kind] || (a.filter ?? '').localeCompare(b.filter ?? ''),
  );
});

/**
 * What a group will receive at calibration, and what it lacks.
 *
 * A missing bias is not reported when a dark covers it: a master dark already contains the
 * bias, and leaving it out is the rule, not an oversight. Only gaps that genuinely degrade
 * the result count — a light without a dark or without a flat, a flat with nothing.
 */
export function calibrationSummary(
  row: GroupRow,
): { has: string; missing: string[] } | null {
  // `match` and not `m`: `m` is now the translated-messages object, and shadowing it here
  // would make the module unreadable. The roles (`bias`, `dark`, `flat`) are astro vocabulary
  // identical in both languages — they do not go through the catalogue.
  const match = row.calibration;
  if (!match) return null;
  const has: string[] = [];
  if (match.bias) has.push('bias');
  if (match.dark) {
    has.push(match.dark_scale === 1 ? 'dark' : `dark ×${match.dark_scale.toFixed(2)}`);
  }
  if (match.flat) has.push('flat');

  const missing: string[] = [];
  if (row.kind === 'light') {
    if (!match.dark) missing.push('dark');
    if (!match.flat) missing.push('flat');
  } else if (!match.bias && !match.dark) {
    missing.push('bias');
  }
  return { has: has.join(' + '), missing };
}

/**
 * Duration spelled out — "20 min", "3 h 20".
 *
 * Seconds are only shown below the minute: nobody reads "12,000 s".
 */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')}`;
}

/** Size spelled out, in decimal units (the ones disk manufacturers use). */
export function formatBytes(bytes: number | null): string {
  if (bytes === null || !Number.isFinite(bytes)) return '—';
  // The byte symbols are *translated*: "Go" has no currency in English, which writes
  // "GB". The prefixes stay decimal in both languages.
  const unites = [
    m.pipeline_unit_b(),
    m.pipeline_unit_kb(),
    m.pipeline_unit_mb(),
    m.pipeline_unit_gb(),
    m.pipeline_unit_tb(),
  ];
  let valeur = bytes;
  let rang = 0;
  while (valeur >= 1000 && rang < unites.length - 1) {
    valeur /= 1000;
    rang += 1;
  }
  return `${valeur.toFixed(rang === 0 || valeur >= 100 ? 0 : 1)} ${unites[rang]}`;
}

/** The cumulative exposure of every final image — the night's total. */
export const totalIntegration = computed<number | null>(() => {
  const produits = plan.value?.products ?? [];
  const connus = produits.filter((p) => p.integration !== null);
  return connus.length ? connus.reduce((somme, p) => somme + (p.integration ?? 0), 0) : null;
});

/** True if the plan announces more data than the disk has room for. */
export const diskShort = computed<boolean>(() => {
  const disque = plan.value?.disk;
  return disque?.free_bytes != null && disque.total_bytes > disque.free_bytes;
});

/** Head count of each group, by key — enough to name the masters of a chain. */
export const groupSizes = computed<Record<string, number>>(() =>
  Object.fromEntries((survey.value?.groups ?? []).map((g) => [g.key, g.count])),
);

/** The groups whose matching left a remark — the list of the real problems. */
export const groupWarnings = computed<{ key: string; note: string }[]>(() =>
  groupRows.value.flatMap((row) =>
    (row.calibration?.notes ?? []).map((note) => ({ key: row.key, note })),
  ),
);

/** Where the user stands — drives which buttons are enabled. */
export type Stage = 'folder' | 'scanned' | 'planned' | 'running' | 'done';

export const stage = computed<Stage>(() => {
  if (running.value) return 'running';
  if (report.value) return 'done';
  if (plan.value) return 'planned';
  if (inventory.value) return 'scanned';
  return 'folder';
});

// --- actions ----------------------------------------------------------------------------

function fail(e: unknown): void {
  error.value = e instanceof Error ? e.message : String(e);
}

export async function loadPresets(): Promise<void> {
  try {
    presets.value = await client.call<PresetInfo[]>('pipeline.presets');
  } catch (e) {
    fail(e);
  }
}

export async function scan(path: string): Promise<void> {
  busy.value = true;
  error.value = '';
  // a new folder invalidates everything downstream: an empty screen beats a plan that
  // would describe the previous folder
  plan.value = null;
  report.value = null;
  try {
    folder.value = path;
    inventory.value = await client.call<Inventory>('pipeline.scan', { path });
    await refreshSurvey();
  } catch (e) {
    inventory.value = null;
    survey.value = null;
    fail(e);
  } finally {
    busy.value = false;
  }
}

/**
 * Change the preset — and regroup, which is the whole point.
 *
 * The preset carries the grouping tolerances, so it governs the table shown one section
 * above. Setting it without re-surveying left the user reading a grouping the plan would
 * *not* build: on a Seestar, one dark group per exposure on screen and a single one in the
 * plan. Only the "smart telescope folder" entry escaped it, because it sets the preset before
 * scanning — which is the shape this function gives every other path.
 */
export async function setPreset(name: string): Promise<void> {
  if (preset.value === name) return;
  preset.value = name;
  // The plan described the previous preset's steps: it is stale by construction.
  plan.value = null;
  planStale.value = true;
  if (!inventory.value) return;
  busy.value = true;
  try {
    await refreshSurvey();
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}

/** Ask the domain for its grouping again — after a scan, after every correction. */
async function refreshSurvey(): Promise<void> {
  survey.value = inventory.value
    ? await client.call<SurveyInfo>('pipeline.survey', {
        inventory: inventory.value,
        // The preset carries the grouping tolerances: without it the table would show
        // groups the plan would not build (a Seestar, whose sensor is unregulated, would
        // make one dark group per exposure).
        preset: preset.value,
      })
    : null;
}

/**
 * Fix the kind of misdetected frames.
 *
 * The call goes through the server even though the inventory lives here: that is
 * deliberate. The correction is a domain operation, and it is the server that echoes the
 * equivalent Python into the console — the wizard has no power of its own.
 */
export async function reclassify(paths: string[], kind: Kind): Promise<void> {
  await mutate('pipeline.reclassify', { paths, kind });
}

/** Drop frames from processing (or bring them back in). */
export async function setExcluded(paths: string[], excluded: boolean): Promise<void> {
  await mutate('pipeline.exclude', { paths, excluded });
}

async function mutate(method: string, params: Record<string, unknown>): Promise<void> {
  if (!inventory.value) return;
  busy.value = true;
  error.value = '';
  try {
    inventory.value = await client.call<Inventory>(method, {
      inventory: inventory.value,
      ...params,
    });
    await refreshSurvey();
    // the plan described the previous inventory: keeping it on screen would be a lie
    plan.value = null;
    planStale.value = true;
    report.value = null;
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}

/** Step unfolded in the plan editor (`null` = none). */
export const selectedStep = signal<string | null>(null);

/**
 * Set a parameter of a plan step.
 *
 * The plan travels both ways, as with frame selection: the server validates, echoes the
 * equivalent Python, and returns the corrected plan. Nothing is modified locally — a
 * rejected value must leave the display on the plan's real state, not on what was typed.
 */
export async function setStepParams(
  stepId: string,
  index: number,
  values: Record<string, unknown>,
): Promise<void> {
  await editPlan('pipeline.set_step_params', { step_id: stepId, index, values });
}

/** Attach (or remove, with `null`) a script run around a step. */
export async function setHooks(
  stepId: string,
  hooks: { before?: string | null; after?: string | null },
): Promise<void> {
  await editPlan('pipeline.set_hooks', { step_id: stepId, ...hooks });
}

async function editPlan(method: string, params: Record<string, unknown>): Promise<void> {
  if (!plan.value) return;
  busy.value = true;
  error.value = '';
  try {
    plan.value = await client.call<PlanInfo>(method, { plan: plan.value, ...params });
    // The report described the previous plan: keeping it on screen would be a lie.
    report.value = null;
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}

/** Open a produced image in the viewport — same API as File → Open. */
/**
 * Open Blink over the light frames of the inventory.
 *
 * Blink existed but was an island: reaching it meant the File menu or the palette, and its
 * `frames` parameter then had to be filled by hand — re-picking, one by one, the very files
 * the wizard had just scanned. Yet reviewing the subs happens *here*, between the scan and the
 * run, and its verdict (`pipeline.exclude`) feeds this same inventory.
 *
 * Lights only: nobody blinks a bias. Excluded frames stay in the sequence — they are exactly
 * what one comes back to look at before restoring them.
 */
export function blinkLights(): void {
  const frames = (inventory.value?.frames ?? [])
    .filter((f) => f.kind === 'light')
    .map((f) => f.path);
  if (!frames.length) return;
  // `layout.open_process` seeds the form, so the panel opens on the sequence rather than on
  // an empty file list. Echoed by the domain, like every layout gesture.
  void client
    .call('layout.open_process', { process_id: 'Blink', values: { frames } })
    .catch((e: unknown) => console.error(e));
}

/**
 * Open an integration — and make it visible.
 *
 * A stack comes out **linear**: its sky background sits around 1e-3, so the window that opens
 * after twenty minutes of computation is, to the eye, black. Every beginner's guide starts by
 * telling people to auto-stretch, which means the first thing the application does with the
 * result of its own pipeline is hand over something that looks like a failure. The screen
 * stretch touches no pixel, and it is exactly what `app.open` followed by `app.compute_auto_stf`
 * would do in the console — two calls, two echoes, nothing the user cannot undo or redo.
 */
export function openResult(path: string): void {
  void client
    .call('app.open', { path })
    .then(() => client.call('app.compute_auto_stf'))
    .catch(fail);
}

export async function buildPlan(): Promise<void> {
  if (!inventory.value) return;
  busy.value = true;
  error.value = '';
  report.value = null;
  try {
    planStale.value = false;
    plan.value = await client.call<PlanInfo>('pipeline.plan', {
      inventory: inventory.value,
      preset: preset.value,
    });
  } catch (e) {
    plan.value = null;
    fail(e);
  } finally {
    busy.value = false;
  }
}

export async function start(): Promise<void> {
  if (!plan.value) return;
  error.value = '';
  report.value = null;
  try {
    const reponse = await client.call<{ job: string }>('pipeline.run', { plan: plan.value });
    jobId.value = reponse.job;
  } catch (e) {
    fail(e);
  }
}

export function cancel(): void {
  if (!jobId.value) return;
  void client.call('process.cancel', { job: jobId.value }).catch(fail);
}

/** Wire the report retrieval to the end of the preprocessing job. */
export function connectPipeline(): void {
  client.onNotification((method, params) => {
    const data = params as { job?: string; id?: string; result?: RunReport; message?: string };
    const id = data.job ?? data.id;
    if (!id || id !== jobId.value) return;
    if (method === 'job.done') {
      // the report travels with the notification: nothing to query
      report.value = data.result ?? null;
      jobId.value = null;
    } else if (method === 'job.error' || method === 'job.cancelled') {
      if (data.message) error.value = data.message;
      jobId.value = null;
    }
  });
}

/** Reset the wizard — useful after a run, to chain another one. */
export function reset(): void {
  inventory.value = null;
  survey.value = null;
  plan.value = null;
  report.value = null;
  error.value = '';
  jobId.value = null;
}
