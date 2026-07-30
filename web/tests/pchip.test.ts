// Curve-interpolation parity: the plot has to show what the computation will do.
//
// A divergence between the editor and `processes/curves.py::_pchip` would break nothing
// visible — the displayed curve would simply stop matching the applied result. That is exactly
// the kind of bug you only find by comparing two images by hand.

import { describe, expect, it } from 'vitest';

import { pchip } from '../src/processes/CurveEditor';
import fixture from './fixtures/pchip.json';

type Point = [number, number];

describe('PCHIP — parity with processes/curves.py', () => {
  it.each(fixture.cases.map((kase, index) => [index, kase] as const))(
    'case %i: same output as the domain',
    (_index, kase) => {
      const points = kase.points as Point[];
      let worst = 0;
      fixture.x.forEach((x, i) => {
        worst = Math.max(worst, Math.abs(pchip(points, x) - kase.expected[i]!));
      });
      expect(worst).toBeLessThan(1e-9);
    },
  );

  it('preserves monotonicity on increasing points', () => {
    // This is the property that made us pick Fritsch–Carlson: a natural spline would overshoot,
    // and the overshoot shows up as local contrast inversions.
    const points: Point[] = [
      [0, 0],
      [0.2, 0.05],
      [0.5, 0.6],
      [0.8, 0.95],
      [1, 1],
    ];
    let previous = -Infinity;
    for (let i = 0; i <= 200; i++) {
      const y = pchip(points, i / 200);
      expect(y).toBeGreaterThanOrEqual(previous - 1e-12);
      previous = y;
    }
  });

  it('never overshoots its control points', () => {
    const points: Point[] = [
      [0, 0.2],
      [0.5, 0.8],
      [1, 0.3],
    ];
    const lo = Math.min(...points.map((p) => p[1]));
    const hi = Math.max(...points.map((p) => p[1]));
    for (let i = 0; i <= 200; i++) {
      const y = pchip(points, i / 200);
      expect(y).toBeGreaterThanOrEqual(lo - 1e-12);
      expect(y).toBeLessThanOrEqual(hi + 1e-12);
    }
  });

  it('is constant outside the range of the points', () => {
    const points: Point[] = [
      [0.2, 0.3],
      [0.8, 0.7],
    ];
    expect(pchip(points, 0)).toBeCloseTo(0.3, 12);
    expect(pchip(points, 1)).toBeCloseTo(0.7, 12);
  });
});
