// Pairing of the manual registration's control points — pure logic.
//
// The process expects two **flat** lists of the same length (`source`, `target`, in pixels).
// The state machine that fills them fits in one rule: a source point is expected when the two
// lists have the same length, a target point otherwise. Writing that inside the component
// would make it unverifiable, when it is precisely the part we want to be sure of — a pair
// shifted by one notch produces a plausible and wrong registration.

/** A complete pair, in image pixels of their respective views. */
export interface Pair {
  sx: number;
  sy: number;
  tx: number;
  ty: number;
}

/** What the next click will lay down. */
export type Expecting = 'source' | 'target';

export function expecting(source: readonly number[], target: readonly number[]): Expecting {
  return source.length === target.length ? 'source' : 'target';
}

/** Complete pairs. A source point without its target does not form one and is not listed. */
export function pairs(source: readonly number[], target: readonly number[]): Pair[] {
  const complet = Math.min(Math.floor(source.length / 2), Math.floor(target.length / 2));
  return Array.from({ length: complet }, (_, i) => ({
    sx: source[i * 2]!, sy: source[i * 2 + 1]!,
    tx: target[i * 2]!, ty: target[i * 2 + 1]!,
  }));
}

/** Source point awaiting its target, if there is one. */
export function pendingSource(
  source: readonly number[],
  target: readonly number[],
): readonly [number, number] | null {
  if (expecting(source, target) === 'source') return null;
  const i = Math.floor(target.length / 2);
  return [source[i * 2]!, source[i * 2 + 1]!];
}

/**
 * Add a click to the right list.
 *
 * Rounded to the half pixel? No: the process works in floats and a control point gains from
 * keeping its sub-pixel precision — that is what distinguishes a fitted transformation from an
 * approximate one.
 */
export function addPoint(
  source: readonly number[],
  target: readonly number[],
  point: readonly [number, number],
): { source: number[]; target: number[] } {
  if (expecting(source, target) === 'source') {
    return { source: [...source, point[0], point[1]], target: [...target] };
  }
  return { source: [...source], target: [...target, point[0], point[1]] };
}

/** Remove the last pair — or the pending source point, if there is one. */
export function removeLast(
  source: readonly number[],
  target: readonly number[],
): { source: number[]; target: number[] } {
  if (expecting(source, target) === 'target') {
    // A source laid down but not paired: that is what we undo, not the previous pair.
    return { source: source.slice(0, -2), target: [...target] };
  }
  return { source: source.slice(0, -2), target: target.slice(0, -2) };
}

/**
 * Overlays of a list of points, numbered.
 *
 * Numbered because the pairing is invisible otherwise: two clouds of crosses on two images do
 * not say which point goes with which, and that is precisely what one checks before launching.
 */
export function toOverlays(
  points: readonly number[],
  color: readonly number[],
): Array<Record<string, unknown>> {
  const count = Math.floor(points.length / 2);
  if (count === 0) return [];
  const positions = Array.from({ length: count }, (_, i) => [points[i * 2]!, points[i * 2 + 1]!]);
  return [
    { kind: 'markers', points: positions, color, size: 11 },
    {
      kind: 'text',
      items: positions.map(([x, y], i) => ({ x: x! + 7, y: y! - 6, text: String(i + 1) })),
      color,
      size: 11,
    },
  ];
}

/** The domain demands at least two complete pairs — the panel must say so before sending. */
export function readyToApply(source: readonly number[], target: readonly number[]): boolean {
  return pairs(source, target).length >= 2;
}
