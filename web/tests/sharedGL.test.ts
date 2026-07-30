// The pure functions of the shared context: the y-flip of the blit and the growth of the canvas.
//
// The y-flip is THE test worth its weight in gold: the rendered region is anchored to the GL
// origin (bottom-left corner), and a wrong `sy` breaks nothing noisy — we blit the wrong band of
// a larger canvas, and the image looks shifted or empty depending on the sizes. Exactly the kind
// of bug that takes an hour to spot.

import { describe, expect, it } from 'vitest';

import { blitSourceRect, nextCanvasSize } from '../src/viewport/sharedGL';

describe('blitSourceRect — the GL → 2D y-flip', () => {
  it('region = canvas: full blit from the origin', () => {
    expect(blitSourceRect(600, 800, 600)).toEqual({ sx: 0, sy: 0, sw: 800, sh: 600 });
  });

  it('region smaller than the canvas: it sits at the BOTTOM, so sy = glHeight − h', () => {
    // A panel 400 tall inside a 1000-tall GL canvas: GL draws its rows 0..400 starting from the
    // bottom, which the 2D frame reads at rows 600..1000.
    expect(blitSourceRect(1000, 640, 400)).toEqual({ sx: 0, sy: 600, sw: 640, sh: 400 });
  });

  it('never returns a negative sy (race between resize and blit)', () => {
    expect(blitSourceRect(300, 640, 400).sy).toBe(0);
  });
});

describe('nextCanvasSize — grow-only growth', () => {
  it('grows component by component, independently', () => {
    // A wide viewport then a tall one: the canvas must cover the union, not the latest.
    expect(nextCanvasSize([800, 200], [400, 600], 16384)).toEqual([800, 600]);
  });

  it('never shrinks — reallocation is the cost we refuse to pay twice', () => {
    expect(nextCanvasSize([1920, 1080], [640, 480], 16384)).toEqual([1920, 1080]);
  });

  it('clamps to the GPU limits', () => {
    expect(nextCanvasSize([1, 1], [40000, 500], 16384)).toEqual([16384, 500]);
  });

  it('never goes below 1×1 (a zero-sized canvas loses its context on some engines)', () => {
    expect(nextCanvasSize([0, 0], [0, 0], 16384)).toEqual([1, 1]);
  });
});
