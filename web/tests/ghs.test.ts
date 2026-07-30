// GHS curve parity: the panel has to plot what the domain will apply.
//
// The five sub-families of the equation (b = −1, b < 0, b = 0, b = 1, b > 0) are *different*
// formulas, selected by the value of b. That is exactly the kind of place where a port starts
// diverging on a single branch without anything breaking: the displayed curve would simply
// stop describing the result.

import { describe, expect, it } from 'vitest';

import fixture from './fixtures/ghs.json';
import { ghsTransfer } from '../src/processes/ghs';

const parametersOf = (kase: (typeof fixture.cases)[number]) => ({
  stretchFactor: kase.stretch_factor,
  localIntensity: kase.local_intensity,
  symmetryPoint: kase.symmetry_point,
  protectShadows: kase.protect_shadows,
  protectHighlights: kase.protect_highlights,
  invert: kase.invert,
});

describe('GHS — parity with processes/stretch.py', () => {
  it.each(fixture.cases.map((kase, index) => [index, kase] as const))(
    'case %i: same output as the domain',
    (_index, kase) => {
      const p = parametersOf(kase);
      let worst = 0;
      fixture.x.forEach((x, i) => {
        worst = Math.max(worst, Math.abs(ghsTransfer(x, p) - kase.expected[i]!));
      });
      expect(worst).toBeLessThan(1e-9);
    },
  );

  it('stays monotonically increasing across every sub-family', () => {
    // A non-monotonic tone curve inverts contrast locally — the defect is immediately visible
    // in the image, but not in a comparison of isolated values.
    for (const b of [-4, -1, -0.5, 0, 0.5, 1, 8, 15]) {
      const p = {
        stretchFactor: 3,
        localIntensity: b,
        symmetryPoint: 0.2,
        protectShadows: 0.05,
        protectHighlights: 0.9,
      };
      let previous = -Infinity;
      for (let i = 0; i <= 400; i++) {
        const y = ghsTransfer(i / 400, p);
        expect(y).toBeGreaterThanOrEqual(previous - 1e-12);
        previous = y;
      }
    }
  });

  it('treats a zero factor as the identity', () => {
    const p = {
      stretchFactor: 0,
      localIntensity: 7,
      symmetryPoint: 0.3,
      protectShadows: 0.1,
      protectHighlights: 0.8,
    };
    for (let i = 0; i <= 20; i++) {
      expect(ghsTransfer(i / 20, p)).toBeCloseTo(i / 20, 12);
    }
  });
});
