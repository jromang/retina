// Sizes of the three collapsible zones — a module signal, not `useState`.
//
// They used to live in `Workbench`, which made them unreachable from the outside: a
// saved perspective did not carry them (although the docstring of `layout_backend.py` claimed
// to serialize "dockview's opaque JSON"), and a reopened project fell back on the
// default values.
//
// These really are **shell preferences**, not domain state: that is why they
// travel in the blob of perspectives and projects, and not in the snapshot.

import { signal } from '@preact/signals';

export interface ZoneSizes {
  sidebar: number;
  right: number;
  bottom: number;
}

export const DEFAULT_ZONE_SIZES: ZoneSizes = { sidebar: 260, right: 300, bottom: 180 };

export const zoneSizes = signal<ZoneSizes>({ ...DEFAULT_ZONE_SIZES });

export function setZoneSize(zone: keyof ZoneSizes, value: number): void {
  zoneSizes.value = { ...zoneSizes.value, [zone]: value };
}

/**
 * Applies sizes read back from a blob, ignoring anything that is not a usable number.
 *
 * A perspective saved **before** this field does not carry it: it must be read back without
 * breaking anything, hence the tolerance rather than a strict schema.
 */
export function applyZoneSizes(saved: unknown): void {
  if (typeof saved !== 'object' || saved === null) return;
  const candidate = saved as Partial<Record<keyof ZoneSizes, unknown>>;
  const next = { ...zoneSizes.value };
  for (const zone of ['sidebar', 'right', 'bottom'] as const) {
    const value = candidate[zone];
    if (typeof value === 'number' && Number.isFinite(value) && value > 0) next[zone] = value;
  }
  zoneSizes.value = next;
}
