// STF parity: the MTF ported to TS/GLSL has to reproduce model/stf.py.
//
// This test covers the reference TypeScript function (`applyChannelStf`), deliberately written
// identically to the GLSL in shaders.ts. The shader itself was verified on a GPU during
// prototyping — offscreen render, read back, 0.49 LSB of deviation — which cannot be replayed
// in CI without a graphics machine. Here we pin the formula down; the GPU runs the same one.

import { describe, expect, it } from 'vitest';

import { applyChannelStf, mtf } from '../src/viewport/shaders';
import stf from './fixtures/stf.json';

describe('MTF — parity with model/stf.py', () => {
  it.each(stf.channels.map((channel, index) => [index, channel] as const))(
    'channel %i: output identical to the domain over the whole range',
    (_index, channel) => {
      let worst = 0;
      stf.raw.forEach((x, i) => {
        const got = applyChannelStf(x, channel.shadows, channel.midtones, channel.highlights);
        worst = Math.max(worst, Math.abs(got - channel.expected[i]!));
      });
      // float32 on the Python side against float64 on the JS side: the tolerable deviation is
      // that of single precision, not a comfort margin.
      expect(worst).toBeLessThan(1e-6);
    },
  );

  it('reproduces the edge cases (m ≤ 0, m ≥ 1, m = 0.5)', () => {
    for (const kase of stf.edge_cases) {
      stf.raw.forEach((x, i) => {
        expect(mtf(kase.midtones, x)).toBeCloseTo(kase.expected[i]!, 6);
      });
    }
  });

  it('is monotonically increasing under an aggressive stretch', () => {
    const channel = stf.channels[0]!;
    let previous = -Infinity;
    for (const x of stf.raw) {
      const y = applyChannelStf(x, channel.shadows, channel.midtones, channel.highlights);
      expect(y).toBeGreaterThanOrEqual(previous - 1e-9);
      previous = y;
    }
  });

  it('bounds the output within [0, 1] even outside the input range', () => {
    const channel = stf.channels[0]!;
    for (const x of [-5, -0.001, 0, 0.5, 1, 1.001, 42]) {
      const y = applyChannelStf(x, channel.shadows, channel.midtones, channel.highlights);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(1);
    }
  });

  it('shows that a 4096-entry LUT would lose what the analytic form keeps', () => {
    // Quantifies the measurement that motivated dropping the LUT: under a typical auto-stretch,
    // sampling the MTF over 4096 uniform steps costs several LSB in the shadows — right where
    // every sky-background pixel lives.
    const channel = stf.channels[0]!;
    const N = 4096;
    const lut = Array.from({ length: N }, (_, i) =>
      applyChannelStf(i / (N - 1), channel.shadows, channel.midtones, channel.highlights),
    );
    let worstLsb = 0;
    for (const x of stf.raw) {
      const exact = applyChannelStf(x, channel.shadows, channel.midtones, channel.highlights);
      const nearest = lut[Math.round(x * (N - 1))]!;
      worstLsb = Math.max(worstLsb, Math.abs(exact - nearest) * 255);
    }
    expect(worstLsb).toBeGreaterThan(1);
  });
});
