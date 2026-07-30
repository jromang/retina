// State machine of the clone stamp.
//
// The rule "one click arms, the next one drops" looks too simple to break. It breaks on the
// third click if the source is not disarmed: we would then drop an operation from a source that
// was already consumed, and the mistake would only show up in the pixels.
//
// Since the tool paints by dragging, a second invariant applies: a press-and-release without
// movement must yield **exactly** the single-disc operation of before. The historical gesture is
// the degenerate case of the new one — if it diverged, every recipe already written would change
// meaning.

import { describe, expect, it } from 'vitest';

import {
  EMPTY_CLONE_STATE,
  STROKE_SPACING,
  beginStroke,
  disarm,
  endStroke,
  extendStroke,
  popOp,
  removeOp,
  toContainer,
  toOverlays,
} from '../src/processes/cloneOps';

const R = 8;
const S = 0.3;

/**
 * A single stamp, as done with the pointer: click the source, then press and release on the
 * destination.
 *
 * There is no separate "click" function any more — the single disc is a one-point stroke. This
 * test shorthand says so, and underpins everything that talks about dropped operations.
 */
const stamp = (
  state = EMPTY_CLONE_STATE,
  src: readonly [number, number] = [0, 0],
  dst: readonly [number, number] = [10, 10],
  radius = R,
  softness = S,
) => endStroke(beginStroke(beginStroke(state, src, radius, softness), dst, radius, softness));

describe('two presses make one operation', () => {
  it('the first press arms the source, dropping nothing', () => {
    const state = beginStroke(EMPTY_CLONE_STATE, [10, 20], R, S);
    expect(state.armed).toEqual([10, 20]);
    expect(state.ops).toHaveLength(0);
  });

  it('the second drops the operation and DISARMS', () => {
    const state = stamp(EMPTY_CLONE_STATE, [10, 20], [50, 60]);
    expect(state.ops).toEqual([
      { srcX: 10, srcY: 20, dstX: 50, dstY: 60, radius: 8, softness: 0.3, points: [] },
    ]);
    // The source **disarms** itself: without that, a third click would drop an operation from a
    // source we believed consumed, and the mistake would only show up in the pixels.
    expect(state.armed).toBeNull();
  });

  it('a third press starts a new pair, it does not complete the previous one', () => {
    const state = beginStroke(stamp(EMPTY_CLONE_STATE, [10, 20], [50, 60]), [11, 21], R, S);
    expect(state.ops).toHaveLength(1);
    expect(state.armed).toEqual([11, 21]);
    expect(state.stroke).toBeNull();
  });

  it('rounds to integers — the process parameters are integers', () => {
    const state = stamp(EMPTY_CLONE_STATE, [10.4, 20.6], [50.5, 60.2]);
    expect(state.ops[0]).toMatchObject({ srcX: 10, srcY: 21, dstX: 51, dstY: 60 });
  });

  it('captures the CURRENT radius, not the one in effect when applied', () => {
    // Changing the radius between two stamps must give two stamps of different sizes —
    // otherwise the setting would only serve the last one.
    let state = stamp(EMPTY_CLONE_STATE, [0, 0], [10, 10], 4, 0);
    state = stamp(state, [20, 20], [30, 30], 12, 0.5);
    expect(state.ops.map((op) => op.radius)).toEqual([4, 12]);
    expect(state.ops.map((op) => op.softness)).toEqual([0, 0.5]);
  });
});

describe('painting by dragging', () => {
  it('the first press arms the source and starts NO stroke', () => {
    const state = beginStroke(EMPTY_CLONE_STATE, [10, 20], R, S);
    expect(state.armed).toEqual([10, 20]);
    expect(state.stroke).toBeNull();
  });

  it('press then release without moving = the single-disc operation of before', () => {
    // The compatibility invariant: the two-click gesture has not changed its result.
    let state = beginStroke(EMPTY_CLONE_STATE, [10, 20], R, S);
    state = beginStroke(state, [50, 60], R, S);
    state = endStroke(state);
    expect(state.ops).toEqual(stamp(EMPTY_CLONE_STATE, [10, 20], [50, 60]).ops);
    expect(state.ops[0]!.points).toEqual([]);
    expect(state.armed).toBeNull();
  });

  it('adds a point only once far enough from the last one', () => {
    let state = beginStroke(beginStroke(EMPTY_CLONE_STATE, [0, 0], 20, S), [100, 100], 20, S);
    const before = state;
    // threshold = 0.25 × 20 = 5 px: two pixels are not enough, and the state must be returned
    // **identical** (same object) so that a mouse move does not trigger a render.
    state = extendStroke(state, [102, 102]);
    expect(state).toBe(before);
    state = extendStroke(state, [110, 100]);
    expect(state.stroke!.points).toEqual([100, 100, 110, 100]);
  });

  it('a threshold of at least one pixel, even with a tiny radius', () => {
    // 0.25 × 1 = 0.25 px: without a floor, two points would round to the same pixel and we
    // would stamp twice in the same place — more opaque at the edge, and paid for twice.
    let state = beginStroke(beginStroke(EMPTY_CLONE_STATE, [0, 0], 1, S), [50, 50], 1, S);
    state = extendStroke(state, [50.3, 50.2]);
    expect(state.stroke!.points).toEqual([50, 50]);
    state = extendStroke(state, [51, 50]);
    expect(state.stroke!.points).toEqual([50, 50, 51, 50]);
  });

  it('the spacing follows the radius captured at the start of the stroke', () => {
    const big = beginStroke(beginStroke(EMPTY_CLONE_STATE, [0, 0], 40, S), [100, 100], 40, S);
    // 0.25 × 40 = 10 px
    expect(extendStroke(big, [105, 100]).stroke!.points).toEqual([100, 100]);
    expect(extendStroke(big, [112, 100]).stroke!.points).toEqual([100, 100, 112, 100]);
    expect(STROKE_SPACING).toBeLessThan(0.5); // overlap of at least half the disc
  });

  it('a stroke becomes ONE operation carrying its trajectory', () => {
    let state = beginStroke(EMPTY_CLONE_STATE, [10, 10], R, S); // source
    state = beginStroke(state, [40, 40], R, S); // press: start of the stroke
    for (const x of [45, 50, 55, 60]) state = extendStroke(state, [x, 40]);
    state = endStroke(state);
    expect(state.ops).toHaveLength(1);
    expect(state.ops[0]).toMatchObject({ srcX: 10, srcY: 10, dstX: 40, dstY: 40, radius: R });
    expect(state.ops[0]!.points).toEqual([40, 40, 45, 40, 50, 40, 55, 40, 60, 40]);
    expect(state.stroke).toBeNull();
    expect(state.armed).toBeNull();
  });

  it('a move outside a stroke paints nothing', () => {
    // The mouse hovers the viewport constantly; without a guard, every hover would extend a
    // stroke that never started.
    const armed = beginStroke(EMPTY_CLONE_STATE, [10, 10], R, S);
    expect(extendStroke(armed, [200, 200])).toBe(armed);
    expect(endStroke(armed)).toBe(armed);
  });

  it('disarming abandons the stroke in progress', () => {
    let state = beginStroke(beginStroke(EMPTY_CLONE_STATE, [0, 0], R, S), [10, 10], R, S);
    state = extendStroke(state, [30, 10]);
    state = disarm(state);
    expect(state.stroke).toBeNull();
    expect(state.armed).toBeNull();
    expect(state.ops).toHaveLength(0);
  });
});

describe('corrections', () => {
  it('disarms a source dropped by mistake', () => {
    const state = disarm(beginStroke(EMPTY_CLONE_STATE, [10, 20], R, S));
    expect(state.armed).toBeNull();
    expect(state.ops).toHaveLength(0);
  });

  it('removes the last operation', () => {
    let state = stamp();
    state = stamp(state, [20, 20], [30, 30]);
    expect(popOp(state).ops).toHaveLength(1);
    expect(popOp(state).ops[0]).toMatchObject({ dstX: 10 });
  });

  it('removes an operation by index, preserving the order of the others', () => {
    let state = EMPTY_CLONE_STATE;
    for (const n of [1, 2, 3]) state = stamp(state, [n, n], [n * 10, n * 10]);
    const remaining = removeOp(state, 1).ops;
    expect(remaining.map((op) => op.dstX)).toEqual([10, 30]);
  });
});

describe('translation into a recipe', () => {
  it('yields one CloneStamp step per operation, in order', () => {
    let state = stamp(EMPTY_CLONE_STATE, [1, 2], [3, 4]);
    state = stamp(state, [5, 6], [7, 8]);
    const steps = toContainer(state.ops);
    expect(steps).toHaveLength(2);
    expect(steps[0]!.process_id).toBe('CloneStamp');
    // The keys are the process's stable C identifiers, not names invented on the client side:
    // that is what makes the recipe readable back by the domain. A single stamp emits **no**
    // `points`: its recipe stays word for word the one it had before strokes existed.
    expect(Object.keys(steps[0]!.values).sort()).toEqual([
      'dst_x', 'dst_y', 'radius', 'softness', 'src_x', 'src_y',
    ]);
    expect(steps[1]!.values['dst_x']).toBe(7);
  });

  it('a stroke emits `points`, and its destination is the first point', () => {
    let state = beginStroke(beginStroke(EMPTY_CLONE_STATE, [1, 1], R, S), [20, 20], R, S);
    state = endStroke(extendStroke(state, [40, 20]));
    const values = toContainer(state.ops)[0]!.values;
    expect(values['points']).toEqual([20, 20, 40, 20]);
    // `src − dst` = the stroke's source offset, readable from the serialized instance alone.
    expect([values['src_x'], values['src_y']]).toEqual([1, 1]);
    expect([values['dst_x'], values['dst_y']]).toEqual([20, 20]);
  });

  it('nothing to play back with no operation', () => {
    expect(toContainer([])).toEqual([]);
    expect(toOverlays([])).toEqual([]);
  });
});

describe('overlays', () => {
  it('one line per operation and two markers per operation', () => {
    let state = stamp(EMPTY_CLONE_STATE, [1, 2], [3, 4]);
    state = stamp(state, [5, 6], [7, 8]);
    const overlays = toOverlays(state.ops);
    expect(overlays.map((o) => o['kind'])).toEqual(['lines', 'markers']);
    expect(overlays[0]!['segments']).toHaveLength(2);
    expect(overlays[1]!['points']).toHaveLength(4);
  });

  it('a dropped stroke reads back: its polyline extends the source→destination segment', () => {
    let state = beginStroke(beginStroke(EMPTY_CLONE_STATE, [0, 0], R, S), [10, 10], R, S);
    for (const x of [30, 50]) state = extendStroke(state, [x, 10]);
    state = endStroke(state);
    // 1 source→start segment + 2 segments of the polyline (3 points)
    expect(toOverlays(state.ops)[0]!['segments']).toHaveLength(3);
  });
});
