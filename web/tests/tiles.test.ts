// Pure tiling logic: levels, visible tiles, keys, UV composition.
//
// The most important contract is sharing the formula with the server: a level's dimensions are
// `ceil(dim / scale)`, identical to the per-octave ceil cascade in `server/pixels.py`. A
// one-pixel disagreement would get an edge tile's `?rect=` rejected.

import { describe, expect, it } from 'vitest';

import {
  levelDims,
  needsTiling,
  overviewKey,
  overviewScale,
  scaleForZoom,
  subUv,
  TILE_SIZE,
  tileKey,
  visibleTiles,
} from '../src/viewport/tiles';

describe('levelDims', () => {
  it('equals the per-octave ceil cascade, odd dimensions included', () => {
    // 7 → 4 → 2: ceil(7/4) = 2, and ceil(ceil(7/2)/2) = 2 as well
    expect(levelDims(7, 5, 4)).toEqual([2, 2]);
    expect(levelDims(20000, 15000, 8)).toEqual([2500, 1875]);
    expect(levelDims(2048, 2048, 1)).toEqual([2048, 2048]);
  });
});

describe('needsTiling / overviewScale', () => {
  it('detects the ceiling being exceeded on a single side', () => {
    expect(needsTiling(20000, 4000, 16384)).toBe(true);
    expect(needsTiling(16384, 16384, 16384)).toBe(false);
  });

  it('picks the smallest level that fits the image inside the overview', () => {
    expect(overviewScale(20000, 15000)).toBe(8); // 20000/8 = 2500 ≤ 4096
    expect(overviewScale(8192, 4096)).toBe(2);
    expect(overviewScale(4096, 4096)).toBe(1); // already inside (image not tiled)
    expect(overviewScale(100_000, 100_000)).toBe(32); // 100000/32 = 3125
  });
});

describe('scaleForZoom', () => {
  it('returns full resolution as soon as zoom reaches 1:1', () => {
    expect(scaleForZoom(1, 8)).toBe(1);
    expect(scaleForZoom(2.5, 8)).toBe(1);
  });

  it('follows the octaves when zooming out, at the exact boundaries', () => {
    expect(scaleForZoom(0.5, 8)).toBe(2);
    expect(scaleForZoom(0.51, 8)).toBe(1); // not a full octave yet
    expect(scaleForZoom(0.25, 8)).toBe(4);
    expect(scaleForZoom(0.1, 8)).toBe(8);
  });

  it('clamps to the overview level', () => {
    expect(scaleForZoom(0.001, 8)).toBe(8);
    expect(scaleForZoom(0, 8)).toBe(8);
  });
});

describe('visibleTiles', () => {
  const W = 20000;
  const H = 15000;

  it('covers exactly the visible region at 1:1 zoom', () => {
    const tiles = visibleTiles(
      { center: [10000, 7500], zoom: 1, vw: 1920, vh: 1080 },
      W,
      H,
      1,
    );
    // 1920 px wide centered on x=10000: from 9040 to 10960 → tiles 4 and 5 (at 2048);
    // 1080 px tall centered on y=7500: from 6960 to 8040, inside tile 3 alone
    const xs = [...new Set(tiles.map((t) => t.tx))];
    const ys = [...new Set(tiles.map((t) => t.ty))];
    expect(xs).toEqual([4, 5]);
    expect(ys).toEqual([3]);
    for (const tile of tiles) {
      expect(tile.quad[0]).toBe(tile.rect[0]); // scale 1: quad = rect
      expect(tile.rect[2]).toBeLessThanOrEqual(TILE_SIZE);
    }
  });

  it('clamps edge tiles to the level and image dimensions', () => {
    const tiles = visibleTiles({ center: [W, H], zoom: 1, vw: 800, vh: 600 }, W, H, 1);
    const last = tiles.at(-1);
    expect(last).toBeDefined();
    // level 1: 20000 = 9×2048 + 1568 → the last column is 1568 wide
    expect(last?.rect[2]).toBe(20000 - 9 * TILE_SIZE);
    expect((last?.quad[0] ?? 0) + (last?.quad[2] ?? 0)).toBeLessThanOrEqual(W);
  });

  it('returns empty outside the image', () => {
    expect(visibleTiles({ center: [-9000, -9000], zoom: 1, vw: 100, vh: 100 }, W, H, 1)).toEqual(
      [],
    );
  });

  it('expresses rect in level coordinates and quad in image coordinates', () => {
    const tiles = visibleTiles({ center: [8192, 8192], zoom: 0.5, vw: 512, vh: 512 }, W, H, 2);
    for (const tile of tiles) {
      expect(tile.quad[0]).toBe(tile.rect[0] * 2);
      expect(tile.quad[2]).toBeLessThanOrEqual(tile.rect[2] * 2);
    }
  });
});

describe('keys', () => {
  it('keeps the existing cache’s view:generation prefix', () => {
    expect(tileKey('M31', 4, 2, 3, 1)).toBe('M31:4:s2:3,1');
    expect(overviewKey('M31', 4, 8)).toBe('M31:4:s8:ov');
  });
});

describe('subUv', () => {
  it('is the identity on the full window', () => {
    expect(subUv([0, 0, 1, 1], 0, 0, 1, 1)).toEqual([0, 0, 1, 1]);
  });

  it('composes with a preview’s window — the direct computation agrees', () => {
    // preview covering (0.25, 0.5) → (0.75, 1.0) of the window: uv = [0.25, 0.5, 0.5, 0.5]
    const previewUv: [number, number, number, number] = [0.25, 0.5, 0.5, 0.5];
    // tile covering the right half of the preview
    const composed = subUv(previewUv, 0.5, 0, 0.5, 1);
    expect(composed).toEqual([0.5, 0.5, 0.25, 0.5]);
  });
});
