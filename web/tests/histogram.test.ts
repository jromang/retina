// Redistributing the histogram through a tone transformation.
//
// This is the computation that replaces a server round trip: a point-to-point transformation
// **moves** the bins without changing their counts, so the histogram of the result follows
// exactly from the original one. These tests check that exactness — without it the panel would
// show a plausible but wrong distribution, which is worse than showing nothing.

import { describe, expect, it, vi } from 'vitest';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const { remap } = await import('../src/ui/Histogram');

describe('remap', () => {
  it('leaves the identity untouched', () => {
    const counts = [3, 0, 7, 1];

    expect(remap(counts, (x) => x)).toEqual(counts);
  });

  it('preserves the total pixel count', () => {
    // The invariant the whole approach rests on: a point-to-point mapping neither creates nor
    // destroys a pixel.
    const counts = [5, 12, 0, 3, 9, 1, 44, 2];
    const total = counts.reduce((a, b) => a + b, 0);

    const compressed = remap(counts, (x) => x * x);

    expect(compressed.reduce((a, b) => a + b, 0)).toBe(total);
  });

  it('stacks the bins up where the transformation compresses', () => {
    // Crushing everything to zero must concentrate every pixel into the first bin — that is
    // the degenerate case, and it still has to be right.
    const counts = [1, 2, 3, 4];

    expect(remap(counts, () => 0)).toEqual([10, 0, 0, 0]);
  });

  it('moves towards the high values when the curve rises', () => {
    // A single bin at the bottom of the range, pulled upwards: it must end up at the top, and
    // nowhere else.
    const counts = [8, 0, 0, 0, 0, 0, 0, 0];

    const stretched = remap(counts, () => 1);

    expect(stretched[stretched.length - 1]).toBe(8);
    expect(stretched.slice(0, -1).every((n) => n === 0)).toBe(true);
  });

  it('clamps overflows rather than losing pixels', () => {
    // An expression can leave [0,1] while it is being edited; silently losing the pixels would
    // make the total wrong.
    const counts = [4, 6];

    const overflowed = remap(counts, (x) => x * 10 - 5);

    expect(overflowed.reduce((a, b) => a + b, 0)).toBe(10);
  });

  it('ignores empty bins without moving them', () => {
    const counts = [0, 0, 5, 0];

    expect(remap(counts, (x) => x).reduce((a, b) => a + b, 0)).toBe(5);
  });
});
