// Pairing of the manual-registration control points.
//
// The failure to guard against is not a crash, it is an **off-by-one**: a source list and a
// target list of different lengths produce wrong pairs, registration still succeeds, and the
// image comes out skewed with nothing having flagged it.

import { describe, expect, it } from 'vitest';

import {
  addPoint,
  expecting,
  pairs,
  pendingSource,
  readyToApply,
  removeLast,
  toOverlays,
} from '../src/processes/alignPairs';

describe('source / target alternation', () => {
  it('starts with a source point', () => {
    expect(expecting([], [])).toBe('source');
  });

  it('expects the target as soon as a source is placed', () => {
    const state = addPoint([], [], [10, 20]);
    expect(state.source).toEqual([10, 20]);
    expect(state.target).toEqual([]);
    expect(expecting(state.source, state.target)).toBe('target');
  });

  it('goes back to the source once the pair is closed', () => {
    let state = addPoint([], [], [10, 20]);
    state = addPoint(state.source, state.target, [30, 40]);
    expect(state.target).toEqual([30, 40]);
    expect(expecting(state.source, state.target)).toBe('source');
  });

  it('keeps sub-pixel precision — that is what separates a fit from an approximation', () => {
    const state = addPoint([], [], [10.25, 20.75]);
    expect(state.source).toEqual([10.25, 20.75]);
  });
});

describe('complete pairs', () => {
  it('ignores a source point that is still orphaned', () => {
    // The domain requires lists of equal length: counting an incomplete pair would end up
    // sending it a pairing that is off by one.
    expect(pairs([1, 2, 5, 6], [3, 4])).toEqual([{ sx: 1, sy: 2, tx: 3, ty: 4 }]);
  });

  it('exposes the pending point, so we know which one to pair', () => {
    expect(pendingSource([1, 2, 5, 6], [3, 4])).toEqual([5, 6]);
    expect(pendingSource([1, 2], [3, 4])).toBeNull();
  });

  it('needs at least two pairs before applying', () => {
    expect(readyToApply([1, 2], [3, 4])).toBe(false);
    expect(readyToApply([1, 2, 5, 6], [3, 4, 7, 8])).toBe(true);
  });
});

describe('undo', () => {
  it('undoes the orphaned source first, not the previous pair', () => {
    // Otherwise a misclick followed by "undo" would destroy a correct pair and leave the
    // mistake in place.
    const state = removeLast([1, 2, 5, 6], [3, 4]);
    expect(state.source).toEqual([1, 2]);
    expect(state.target).toEqual([3, 4]);
  });

  it('undoes the last complete pair', () => {
    const state = removeLast([1, 2, 5, 6], [3, 4, 7, 8]);
    expect(state.source).toEqual([1, 2]);
    expect(state.target).toEqual([3, 4]);
  });

  it('breaks nothing on an empty state', () => {
    expect(removeLast([], [])).toEqual({ source: [], target: [] });
  });
});

describe('numbered overlays', () => {
  it('one marker and one label per point', () => {
    const overlays = toOverlays([1, 2, 5, 6], [1, 1, 1, 1]);
    expect(overlays.map((o) => o['kind'])).toEqual(['markers', 'text']);
    expect(overlays[0]!['points']).toEqual([[1, 2], [5, 6]]);
    // Numbered: two clouds of crosses on two images do not say which point goes with which
    // other one, and that is exactly what gets checked before running.
    expect((overlays[1]!['items'] as Array<{ text: string }>).map((i) => i.text)).toEqual(['1', '2']);
  });

  it('nothing to draw without a point', () => {
    expect(toOverlays([], [1, 1, 1, 1])).toEqual([]);
  });
});
