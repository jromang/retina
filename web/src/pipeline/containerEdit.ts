// Recipe editing — the logic, without the DOM.
//
// # Why the list is rebuilt rather than the domain mutated
//
// `ProcessContainer` (on the Python side) offers only `add`: no `insert`, no `remove`, no
// `move`. That is not an oversight — the removed Qt panel already did exactly what this
// module does, namely hold the order on the interface side and **rebuild** the container at
// the moment of running or saving (`container()` in the old `gui/container_panel.py`). Adding
// three methods to the domain to make it carry a transient editing state would be taking the
// problem backwards: a recipe being written is not a recipe yet.
//
// The shape handled is therefore `{process_id, values}` — exactly `Process.to_dict()`, what
// `library.get` returns and what `library.put` and `process.run_container` expect — augmented
// with the two per-step flags (enabled, mask). No conversion anywhere.

import { signal } from '@preact/signals';

import { client } from '../api/client';
import type { ProcessPayload } from '../dnd/dnd';
import { m } from '../paraglide/messages';

export const CONTAINER_PREFIX = 'container:';

/**
 * A recipe step: the instance, plus the two per-step flags.
 *
 * The flags live **on the step** and not in parallel arrays: moving a step then carries its
 * state along without `moveStep` having to know about it. On the Python side the container
 * stores them in parallel, because the indexed API it follows imposes that; the conversion
 * happens once, in `ProcessContainer.to_dicts`/`from_dicts`.
 *
 * Absent keys = default values, as on the wire: an ordinary recipe stays exactly what it
 * was.
 */
export interface RecipeStep extends ProcessPayload {
  enabled?: boolean;
  mask?: string;
  mask_inverted?: boolean;
}

export function isEnabled(step: RecipeStep): boolean {
  return step.enabled !== false;
}

export interface ContainerDoc {
  /** Dockview tab id, stable for the document's whole life — the name, itself, can change. */
  id: string;
  /** Matching library entry, `null` as long as the recipe has not been named. */
  name: string | null;
  title: string;
  steps: readonly RecipeStep[];
  dirty: boolean;
}

export const openContainers = signal<readonly ContainerDoc[]>([]);

let nextId = 1;
let nextUntitled = 1;

// --- pure operations on the step list -------------------------------------

export function insertStep(
  steps: readonly RecipeStep[],
  step: RecipeStep,
  index?: number,
): RecipeStep[] {
  const next = [...steps];
  next.splice(index === undefined ? next.length : clamp(index, 0, next.length), 0, step);
  return next;
}

export function removeStep(steps: readonly RecipeStep[], index: number): RecipeStep[] {
  if (index < 0 || index >= steps.length) return [...steps];
  return steps.filter((_, i) => i !== index);
}

/**
 * Move a step. `to` is the **arrival index in the final list**, not the index of the element
 * to insert in front of — the nuance decides what happens when a step is moved down one
 * notch, where the two conventions differ by one position.
 */
export function moveStep(
  steps: readonly RecipeStep[],
  from: number,
  to: number,
): RecipeStep[] {
  if (from < 0 || from >= steps.length || from === to) return [...steps];
  const next = [...steps];
  const [moved] = next.splice(from, 1);
  if (moved === undefined) return [...steps];
  next.splice(clamp(to, 0, next.length), 0, moved);
  return next;
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}

/** Replace a step with a modified version. Keys left at their default are **removed**. */
function withStep(
  steps: readonly RecipeStep[],
  index: number,
  // explicit `| undefined`: `exactOptionalPropertyTypes` distinguishes "absent key" from
  // "key set to undefined", and it is indeed the second one we write before cleaning up.
  changes: { enabled?: boolean | undefined; mask?: string | undefined; mask_inverted?: boolean },
): RecipeStep[] {
  if (index < 0 || index >= steps.length) return [...steps];
  return steps.map((step, i) => {
    if (i !== index) return step;
    const next = { ...step, ...changes } as RecipeStep;
    // A recipe without flags must serialize as before: re-enabling a step or removing its
    // mask erases the key instead of writing the default value.
    if (next.enabled !== false) delete next.enabled;
    if (!next.mask) {
      delete next.mask;
      delete next.mask_inverted;
    } else if (!next.mask_inverted) {
      delete next.mask_inverted;
    }
    return next;
  });
}

export function setStepEnabled(
  steps: readonly RecipeStep[],
  index: number,
  enabled: boolean,
): RecipeStep[] {
  return withStep(steps, index, { enabled });
}

export function setStepMask(
  steps: readonly RecipeStep[],
  index: number,
  mask: string | null,
  inverted = false,
): RecipeStep[] {
  return withStep(steps, index, { mask: mask ?? undefined, mask_inverted: inverted });
}

// --- open documents -------------------------------------------------------

function patch(id: string, changes: Partial<ContainerDoc>): void {
  openContainers.value = openContainers.value.map((doc) =>
    doc.id === id ? { ...doc, ...changes } : doc,
  );
}

export function containerById(id: string): ContainerDoc | undefined {
  return openContainers.value.find((doc) => doc.id === id);
}

export function newContainer(): string {
  const id = `${CONTAINER_PREFIX}${nextId++}`;
  openContainers.value = [
    ...openContainers.value,
    {
      id,
      name: null,
      title: m.container_untitled({ n: nextUntitled++ }),
      steps: [],
      dirty: false,
    },
  ];
  return id;
}

/** Open a library entry — or bring back its tab, if it is already there. */
export function adoptContainer(name: string, steps: readonly RecipeStep[]): string {
  const existing = openContainers.value.find((doc) => doc.name === name);
  if (existing) return existing.id;
  const id = `${CONTAINER_PREFIX}${nextId++}`;
  openContainers.value = [
    ...openContainers.value,
    { id, name, title: name, steps: [...steps], dirty: false },
  ];
  return id;
}

export function closeContainer(id: string): void {
  openContainers.value = openContainers.value.filter((doc) => doc.id !== id);
}

export function setSteps(id: string, steps: readonly RecipeStep[]): void {
  patch(id, { steps: [...steps], dirty: true });
}

// --- persistence (project) -------------------------------------------------

export interface SerializedContainers {
  docs: ContainerDoc[];
  nextId: number;
  nextUntitled: number;
}

/**
 * The whole state of a recipe in progress is already in the signal — the step flags live on
 * the step, there is no parallel table to stitch back together. Unlike scripts, `dirty` is
 * carried as is: an unnamed recipe has no on-disk reference to compare itself against.
 */
export function serializeContainers(): SerializedContainers {
  return { docs: openContainers.value.map((doc) => ({ ...doc, steps: [...doc.steps] })),
           nextId, nextUntitled };
}

export function restoreContainers(state: SerializedContainers): void {
  const docs: ContainerDoc[] = [];
  for (const doc of state.docs) {
    if (docs.some((existing) => doc.name !== null && existing.name === doc.name)) continue;
    docs.push({ ...doc, steps: [...doc.steps] });
  }
  openContainers.value = docs;
  nextId = Math.max(nextId, state.nextId ?? 1);
  nextUntitled = Math.max(nextUntitled, state.nextUntitled ?? 1);
}

export function markContainerSaved(id: string, name: string): void {
  patch(id, { name, title: name, dirty: false });
}

// --- server ----------------------------------------------------------------

export async function openContainerFromLibrary(name: string): Promise<string> {
  const existing = openContainers.value.find((doc) => doc.name === name);
  if (existing) return existing.id;
  const detail = await client.call<{ processes: RecipeStep[] }>('library.get', { name });
  return adoptContainer(name, detail.processes);
}

export async function saveContainer(id: string, name: string): Promise<void> {
  const doc = containerById(id);
  if (!doc || doc.steps.length === 0) return;
  await client.call('library.put', { name, processes: doc.steps });
  markContainerSaved(id, name);
}
