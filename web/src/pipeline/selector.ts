// Frame selection — the logic, kept apart from the rendering.
//
// This is the screen that was missing: the core already measures FWHM, eccentricity, SNR and
// star count, and derives an integration weight from them; there was no way to *look* at those
// measurements nor to revisit the verdict. Like the rest of the wizard, this module has no
// power of its own: it calls `pipeline.measures`, `pipeline.set_rejects` and
// `pipeline.set_criteria`, and every gesture is written to the console as replayable Python.
//
// Two decisions:
//
//  · **Inspection happens between two runs**, never during one. The measurements are on disk
//    (`retina_pipeline/measures/`), so reading them back, re-judging and relaunching is
//    enough — no blocking modal in the middle of a run, and no pause mechanism to invent.
//  · **Rejecting is not excluding.** A rejected frame is still calibrated and registered; it
//    simply weighs zero in the stack. Going through `pipeline.exclude` would change the
//    inputs of calibration, measurement and registration, hence invalidate their cache: we
//    would pay for the star detection of a hundred exposures to drop six of them.

import { computed, signal } from '@preact/signals';

import { client } from '../api/client';
import { m } from '../paraglide/messages';
import { openResult, plan, report, type PlanInfo } from './model';

/** One frame measurement, as `SubframeSelector` produces it. */
export interface Measurement {
  frame: string;
  index?: number;
  stars: number;
  fwhm: number;
  eccentricity: number;
  snr: number;
  noise: number;
  median: number;
  score: number;
  weight: number;
  approved: boolean;
  /** Why the frame is dropped: `manual`, `expression`, `min_weight`. */
  rejected_by?: string;
  /** Quantities min-max normalised over the batch, where 1 is always the best. */
  [normalised: string]: unknown;
}

/** What a group will yield after selection — **real** cumulative exposure included. */
export interface GroupSummary {
  key: string;
  filter: string | null;
  path: string;
  exposure: number | null;
  /** Count announced by the plan: an upper bound, it ignores rejections. */
  planned: number;
  measured: number;
  /** Count kept after selection — the real figure. */
  frames: number;
  rejected: number;
  rejected_by: Record<string, number>;
  integration: number | null;
}

export interface Criteria {
  approval: string;
  weighting: string;
  min_weight: number;
  roundness_limit: number;
}

export interface MeasuresPayload {
  groups: Record<string, Measurement[]>;
  rejects: Record<string, string[]>;
  criteria: Record<string, Criteria>;
  summary: GroupSummary[];
}

/**
 * The table's columns — **what we actually measure**.
 *
 * `rejected_by` is one of them and is not decorative: it is the column that says *why* an
 * exposure is dropped. Hiding it would leave "master not found" and "master forbidden"
 * indistinguishable, when the two call for opposite gestures.
 */
export interface Column {
  id: string;
  label: string;
  /** Digits after the decimal point; absent = non-numeric value. */
  digits?: number;
  hint?: string;
}

export const COLUMNS: readonly Column[] = [
  { id: 'index', label: m.selector_column_index(), digits: 0 },
  { id: 'name', label: m.selector_column_name() },
  {
    id: 'fwhm',
    label: m.selector_column_fwhm(),
    digits: 2,
    hint: m.selector_column_fwhm_hint(),
  },
  {
    id: 'fwhm_arcsec',
    label: m.selector_column_fwhm_arcsec(),
    digits: 2,
    hint: m.selector_column_fwhm_arcsec_hint(),
  },
  {
    id: 'eccentricity',
    label: m.selector_column_eccentricity(),
    digits: 3,
    hint: m.selector_column_eccentricity_hint(),
  },
  { id: 'snr', label: m.selector_column_snr(), digits: 1 },
  {
    id: 'stars',
    label: m.selector_column_stars(),
    digits: 0,
    hint: m.selector_column_stars_hint(),
  },
  {
    id: 'psf_count',
    label: m.selector_column_psf(),
    digits: 0,
    hint: m.selector_column_psf_hint(),
  },
  {
    id: 'fwhm_mean_dev',
    label: m.selector_column_fwhm_dev(),
    digits: 3,
    hint: m.selector_column_fwhm_dev_hint(),
  },
  {
    id: 'eccentricity_mean_dev',
    label: m.selector_column_ecc_dev(),
    digits: 3,
    hint: m.selector_column_ecc_dev_hint(),
  },
  { id: 'noise', label: m.selector_column_noise(), digits: 5 },
  { id: 'median', label: m.selector_column_median(), digits: 5 },
  {
    id: 'psf_signal_weight',
    label: m.selector_column_psfsw(),
    digits: 4,
    hint: m.selector_column_psfsw_hint(),
  },
  {
    id: 'psf_snr',
    label: m.selector_column_psfsnr(),
    digits: 4,
    hint: m.selector_column_psfsnr_hint(),
  },
  { id: 'weight', label: m.selector_column_weight(), digits: 4 },
  {
    id: 'rejected_by',
    label: m.selector_column_rejected(),
    hint: m.selector_column_rejected_hint(),
  },
];

/** The plottable metrics — the order is that of the chart grid. */
export const METRICS = ['fwhm', 'eccentricity', 'snr', 'stars', 'noise', 'median'] as const;
export type Metric = (typeof METRICS)[number];

/** Columns always present, which are not measurements and have nothing to hide. */
const ALWAYS = new Set(['index', 'name', 'rejected_by']);

// --- state ------------------------------------------------------------------------------

export const measures = signal<MeasuresPayload | null>(null);
export const activeGroup = signal<string>('');
export const sortKey = signal<string>('index');
export const sortAscending = signal<boolean>(true);
/** Highlighted frame — clicking a chart point selects it. */
export const selectedFrame = signal<string>('');
export const loading = signal<boolean>(false);
export const selectorError = signal<string>('');
/** Criterion refused by the domain, shown under the offending field rather than in bulk. */
export const criteriaError = signal<{ key: keyof Criteria; message: string } | null>(null);

/**
 * The registration reference frame, if a run has designated one.
 *
 * It is the exposure that fixes the geometry of all the others — the one that must least be
 * dropped, and the only one whose identity changes the result of the whole group. It comes
 * from the run report, the only place that can know it (the choice is made at run time).
 */
export const referenceFrame = computed<string>(() => report.value?.reference ?? '');

/** The file name alone: full paths make the table unreadable. */
export function basename(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] ?? path;
}

export const groupKeys = computed<string[]>(() =>
  Object.keys(measures.value?.groups ?? {}).sort(),
);

/** The group displayed — the first one with measurements, as long as nothing is chosen. */
export const currentGroup = computed<string>(() => {
  const keys = groupKeys.value;
  if (activeGroup.value && keys.includes(activeGroup.value)) return activeGroup.value;
  return keys.find((k) => (measures.value?.groups[k]?.length ?? 0) > 0) ?? keys[0] ?? '';
});

export const rows = computed<Measurement[]>(
  () => measures.value?.groups[currentGroup.value] ?? [],
);

/**
 * The columns that have something to show.
 *
 * Three of them do not always exist: `fwhm_arcsec` needs the pixel size and the focal length,
 * `psf_count` and the field dispersions only exist with PSF fitting — and measurements written
 * by an earlier version carry none of them. Showing a column of dashes would suggest a zero
 * quantity, which on a dispersion reads as "perfect".
 */
export const visibleColumns = computed<Column[]>(() => {
  const lignes = rows.value;
  if (!lignes.length) return [...COLUMNS];
  return COLUMNS.filter(
    (column) => ALWAYS.has(column.id) || lignes.some((row) => row[column.id] !== undefined),
  );
});

export const currentSummary = computed<GroupSummary | null>(
  () => measures.value?.summary.find((s) => s.key === currentGroup.value) ?? null,
);

export const currentCriteria = computed<Criteria | null>(
  () => measures.value?.criteria[currentGroup.value] ?? null,
);

/** True as soon as one group has measurements — otherwise the screen has nothing to show. */
export const hasMeasures = computed<boolean>(() =>
  Object.values(measures.value?.groups ?? {}).some((list) => list.length > 0),
);

/** A column's sortable value. `index` and `name` are not in the measurement. */
export function cellValue(row: Measurement, index: number, column: string): number | string {
  if (column === 'index') return index;
  if (column === 'name') return basename(row.frame);
  if (column === 'rejected_by') {
    return row.approved ? '' : (row.rejected_by ?? m.selector_reject_unknown());
  }
  const value = row[column];
  return typeof value === 'number' ? value : String(value ?? '');
}

/**
 * The sorted rows, each keeping its **original rank**.
 *
 * That rank is the one of the integration's input list: it is what pairs a measurement with
 * its frame on the domain side. Displaying it sorted by FWHM must not renumber it, otherwise
 * the "#" column would designate a different frame depending on the table's order.
 */
export const sortedRows = computed<{ row: Measurement; index: number }[]>(() => {
  const list = rows.value.map((row, index) => ({ row, index }));
  const key = sortKey.value;
  const sens = sortAscending.value ? 1 : -1;
  return list.sort((a, b) => {
    const va = cellValue(a.row, a.index, key);
    const vb = cellValue(b.row, b.index, key);
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * sens;
    return String(va).localeCompare(String(vb)) * sens;
  });
});

/** Bounds of a metric over the current group — the charts' scale. */
export function metricRange(metric: string): { min: number; max: number } {
  const valeurs = rows.value
    .map((r) => r[metric])
    .filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  if (!valeurs.length) return { min: 0, max: 1 };
  const min = Math.min(...valeurs);
  const max = Math.max(...valeurs);
  // a perfectly uniform batch would flatten the chart onto a line: give it some room
  return max - min > 1e-12 ? { min, max } : { min: min - 0.5, max: max + 0.5 };
}

/** Toggle the sort: same column = flip the direction, other column = restart ascending. */
export function toggleSort(column: string): void {
  if (sortKey.value === column) {
    sortAscending.value = !sortAscending.value;
  } else {
    sortKey.value = column;
    sortAscending.value = true;
  }
}

// --- actions ----------------------------------------------------------------------------

function fail(e: unknown): void {
  selectorError.value = e instanceof Error ? e.message : String(e);
}

/** Read back the current plan's measurements. Without a plan there is nothing to inspect. */
export async function loadMeasures(): Promise<void> {
  const courant = plan.value;
  if (!courant) {
    measures.value = null;
    return;
  }
  loading.value = true;
  selectorError.value = '';
  try {
    measures.value = await client.call<MeasuresPayload>('pipeline.measures', {
      plan: courant,
    });
  } catch (e) {
    measures.value = null;
    fail(e);
  } finally {
    loading.value = false;
  }
}

/**
 * Apply a corrected plan and read the measurements back.
 *
 * The plan comes back from the server at every gesture: it is what carries the rejections and
 * the criteria, and it is what will be handed back to `pipeline.run`. Reading it again is
 * free — the measurements are cached, only the evaluation is redone.
 */
async function apply(method: string, params: Record<string, unknown>): Promise<void> {
  if (!plan.value) return;
  loading.value = true;
  selectorError.value = '';
  try {
    plan.value = await client.call<PlanInfo>(method, { plan: plan.value, ...params });
    measures.value = await client.call<MeasuresPayload>('pipeline.measures', {
      plan: plan.value,
    });
  } catch (e) {
    fail(e);
  } finally {
    loading.value = false;
  }
}

/** Drop a frame from the current group's stack, or bring it back in. */
export async function toggleReject(frame: string): Promise<void> {
  const group = currentGroup.value;
  const actuels = measures.value?.rejects[group] ?? [];
  const paths = actuels.includes(frame)
    ? actuels.filter((p) => p !== frame)
    : [...actuels, frame];
  await apply('pipeline.set_rejects', { group, paths });
}

/** Set the group's complete rejection list — "reset everything", "drop everything". */
export async function setRejects(paths: string[]): Promise<void> {
  await apply('pipeline.set_rejects', { group: currentGroup.value, paths });
}

/**
 * Freeze into manual rejections what the automatic criteria dropped.
 *
 * Without this gesture, changing the expression would silently readmit exposures that had
 * been judged bad. This is the gesture usually named "lock rejections".
 */
export async function freezeRejections(): Promise<void> {
  const ecartees = rows.value.filter((r) => !r.approved).map((r) => r.frame);
  await setRejects(ecartees);
}

/**
 * Set a criterion. Omitting `group` applies it to every group — the common gesture.
 *
 * A faulty expression is refused by the domain **before** it enters the plan: we collect here
 * what is needed to report it under the field concerned, rather than as a global error
 * message that would not say which of the four is at fault.
 */
export async function setCriteria(
  criteria: Partial<Criteria>,
  group?: string,
): Promise<void> {
  criteriaError.value = null;
  const [key] = Object.keys(criteria) as (keyof Criteria)[];
  try {
    await apply('pipeline.set_criteria', {
      criteria,
      ...(group === undefined ? {} : { group }),
    });
  } finally {
    if (key && selectorError.value) {
      criteriaError.value = { key, message: selectorError.value };
      selectorError.value = '';
    }
  }
}

/** Open the judged frame in the viewport — same API as File → Open, hence echoed. */
export function openFrame(frame: string): void {
  selectedFrame.value = frame;
  openResult(frame);
}

/** True if the frame is dropped by hand (and not by an automatic criterion). */
export function isManuallyRejected(frame: string): boolean {
  return (measures.value?.rejects[currentGroup.value] ?? []).includes(frame);
}
