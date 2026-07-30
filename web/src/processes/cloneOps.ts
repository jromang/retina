// State machine of the clone stamp, and its translation into a recipe.
//
// Extracted from the panel so as to be tested without a browser: two clicks form an operation,
// a drag forms a stroke, and the rule "the first click arms, the second lays down" is exactly
// the kind of logic that breaks on the third click without anyone noticing.
//
// # Painting by dragging: one stroke = ONE instance
//
// The stamp was single-disc: each hit was an instance, and the panel played them in a
// `ProcessContainer`. A continuous gesture makes that model untenable — two seconds of mouse
// make dozens of discs, hence as many history entries and as many container rounds for what
// the user experiences as *one stroke*. `CloneStamp` therefore now carries a **trajectory**
// (`points`, a floatlist `[x0,y0,x1,y1,…]` of destinations), the source offset staying
// constant over the whole stroke: that is the classic semantics of a stamp.
//
// The container nevertheless remains the way to send *several* independent strokes or hits
// (different sources): one job, one echo, a guaranteed order — where a loop of `process.run`
// would release N concurrent jobs on a pool of four threads. And it pushes one history entry
// **per step** (`ProcessContainer.execute_on`), hence per stroke: one takes back the last
// brush stroke without undoing everything, which is the right granularity for a retouch.
//
// # Spacing is a client-side decision
//
// The core stamps the points it is given, with no spacing parameter: on its own it would be
// unable to know how fast the mouse moved. So it is here that the points are sown, at
// `STROKE_SPACING × radius` — tight enough for a smooth stroke, loose enough not to pile a
// thousand discs onto ten pixels.

/** Fraction of the radius between two stamps of a stroke. A quarter: wide overlap, modest cost. */
export const STROKE_SPACING = 0.25;

/** One committed operation: source → destination, in image pixels. */
export interface CloneOp {
  srcX: number;
  srcY: number;
  dstX: number;
  dstY: number;
  radius: number;
  softness: number;
  /**
   * Trajectory of the stroke, `[x0,y0,x1,y1,…]` in destinations.
   *
   * **Empty** = single hit: the process then falls back on `dst_x`/`dst_y`, exactly as before
   * strokes existed. Non-empty, `dstX`/`dstY` hold the first point — the serialized instance
   * stays readable on its own, the source offset still reads there as `src − dst`.
   */
  points: readonly number[];
}

/** Stroke being drawn: not an operation yet, but already a source and some points. */
export interface CloneStroke {
  srcX: number;
  srcY: number;
  radius: number;
  softness: number;
  /** At least one pair: the starting point is laid down at the `pointerdown`. */
  points: readonly number[];
}

export interface CloneState {
  /** Operations already laid down, in the order in which they will be played. */
  ops: readonly CloneOp[];
  /** Armed source awaiting its destination, if there is one. */
  armed: readonly [number, number] | null;
  /** Stroke in progress, between the `pointerdown` and the `pointerup`. */
  stroke: CloneStroke | null;
}

export const EMPTY_CLONE_STATE: CloneState = { ops: [], armed: null, stroke: null };

/**
 * `pointerdown`. With no armed source, this is the first click — it arms, it does not paint.
 *
 * With an armed source, the stroke begins: its first point is laid down immediately, so that a
 * press followed by an immediate release (without the slightest movement) gives exactly the
 * single-disc operation of the earlier two clicks. The historical gesture is a special case of
 * the new one, not a separate branch that would drift — there is therefore **no** "click"
 * function alongside the stroke: two entry points for one gesture would end up no longer
 * saying the same thing.
 *
 * The coordinates are **rounded**: the process parameters are integers, and half a pixel means
 * nothing to a stamp.
 */
export function beginStroke(
  state: CloneState,
  point: readonly [number, number],
  radius: number,
  softness: number,
): CloneState {
  const x = Math.round(point[0]);
  const y = Math.round(point[1]);
  if (!state.armed) return { ...state, armed: [x, y], stroke: null };
  return {
    ...state,
    stroke: { srcX: state.armed[0], srcY: state.armed[1], radius, softness, points: [x, y] },
  };
}

/**
 * `pointermove` during the stroke: adds a point if we have moved far enough from the last one.
 *
 * The threshold is `spacing × radius`, **at least one pixel**: below that, two points round to
 * the same pixel and we would stamp twice at the same place — more opaque at the edge, and
 * paid for twice. The state is returned **unchanged** (same object) when the point is
 * rejected, which avoids one render per mouse movement.
 *
 * The radius is not passed in again: it is the one **captured at the start of the stroke**.
 * Reading it elsewhere would allow changing the radius mid-gesture, hence producing a stroke
 * the core — which has only one `radius` per instance — could do nothing with.
 */
export function extendStroke(
  state: CloneState,
  point: readonly [number, number],
  spacing: number = STROKE_SPACING,
): CloneState {
  const stroke = state.stroke;
  if (!stroke) return state;
  const x = Math.round(point[0]);
  const y = Math.round(point[1]);
  const n = stroke.points.length;
  const dx = x - (stroke.points[n - 2] as number);
  const dy = y - (stroke.points[n - 1] as number);
  const seuil = Math.max(spacing * stroke.radius, 1);
  if (Math.hypot(dx, dy) < seuil) return state;
  return { ...state, stroke: { ...stroke, points: [...stroke.points, x, y] } };
}

/**
 * `pointerup`: the stroke becomes an operation, and the source disarms.
 *
 * A one-point stroke falls back on the single-disc operation (`points` empty): the recipe sent
 * is then the same as before, field for field.
 */
export function endStroke(state: CloneState): CloneState {
  const stroke = state.stroke;
  if (!stroke) return state;
  const [x0, y0] = [stroke.points[0] as number, stroke.points[1] as number];
  return {
    ops: [
      ...state.ops,
      {
        srcX: stroke.srcX,
        srcY: stroke.srcY,
        dstX: x0,
        dstY: y0,
        radius: stroke.radius,
        softness: stroke.softness,
        points: stroke.points.length > 2 ? stroke.points : [],
      },
    ],
    armed: null,
    stroke: null,
  };
}

/** Cancel the armed source and the stroke in progress — the way out of the wrong spot. */
export function disarm(state: CloneState): CloneState {
  return { ...state, armed: null, stroke: null };
}

/** Remove an operation by its rank. */
export function removeOp(state: CloneState, index: number): CloneState {
  return { ...state, ops: state.ops.filter((_, i) => i !== index) };
}

/** Remove the last operation laid down — the natural undo gesture before applying. */
export function popOp(state: CloneState): CloneState {
  return { ...state, ops: state.ops.slice(0, -1) };
}

/** Translate the operations into recipe steps, ready for `process.run_container`. */
export function toContainer(
  ops: readonly CloneOp[],
): Array<{ process_id: string; values: Record<string, unknown> }> {
  return ops.map((op) => {
    const values: Record<string, unknown> = {
      src_x: op.srcX,
      src_y: op.srcY,
      dst_x: op.dstX,
      dst_y: op.dstY,
      radius: op.radius,
      softness: op.softness,
    };
    // `points` is only emitted if there is a stroke: a single-hit recipe stays word for word
    // the one from before, readable by a script that knows nothing of trajectories.
    if (op.points.length > 0) values['points'] = [...op.points];
    return { process_id: 'CloneStamp', values };
  });
}

/** Split a flat list `[x,y,…]` into pairs — for drawing. */
function couples(points: readonly number[]): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  for (let i = 0; i + 1 < points.length; i += 2) out.push([points[i] as number, points[i + 1] as number]);
  return out;
}

/** Domain overlays describing the operations laid down: markers + source→destination lines. */
export function toOverlays(ops: readonly CloneOp[]): Array<Record<string, unknown>> {
  if (ops.length === 0) return [];
  const segments: Array<Array<[number, number]>> = [];
  for (const op of ops) {
    segments.push([
      [op.srcX, op.srcY],
      [op.dstX, op.dstY],
    ]);
    // The stroke itself, so that a laid-down gesture can be read back: without it, a stroke
    // of fifty points would leave the same trace on screen as a single hit.
    const path = couples(op.points);
    for (let i = 1; i < path.length; i++) segments.push([path[i - 1] as [number, number], path[i] as [number, number]]);
  }
  return [
    {
      kind: 'lines',
      segments,
      color: [1, 0.6, 0.2, 0.8],
      width: 1,
    },
    {
      kind: 'markers',
      points: ops.flatMap((op) => [
        [op.srcX, op.srcY],
        [op.dstX, op.dstY],
      ]),
      color: [1, 0.6, 0.2, 0.95],
      size: 7,
    },
  ];
}
