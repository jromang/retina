// Channel and transparency conventions — they must say the same thing as the domain.
//
// The reference is `Image.nominal_channels` / `Image.has_alpha`
// (python/retina/model/image.py): C=1 grey, C=2 grey+alpha, C=3 RGB, C=4 RGBA. The trap is
// grey+alpha, which is mono AND transparent: testing it on `channels === 1` made it display
// as an RGB whose green would have been the alpha.

import { describe, expect, it } from 'vitest';

import {
  hasAlphaChannels,
  isMonoChannels,
  TRANSPARENCY_CODE,
  transparencyCode,
} from '../src/viewport/shaders';

describe('channel conventions (parity with Image.nominal_channels)', () => {
  it('mono = 1 nominal channel, alpha included', () => {
    expect([1, 2, 3, 4].map(isMonoChannels)).toEqual([true, true, false, false]);
  });

  it('alpha present for grey+alpha and for RGBA', () => {
    expect([1, 2, 3, 4].map(hasAlphaChannels)).toEqual([false, true, false, true]);
  });
});

describe('transparency modes (parity with TransparencyMode)', () => {
  it('translates the three modes of the domain', () => {
    expect(transparencyCode('hide')).toBe(TRANSPARENCY_CODE.hide);
    expect(transparencyCode('brush')).toBe(TRANSPARENCY_CODE.brush);
    expect(transparencyCode('color')).toBe(TRANSPARENCY_CODE.color);
  });

  it('falls back on the checkerboard — the domain default — for an unknown mode', () => {
    // A newer Retina may send a mode this client does not know about: showing the
    // checkerboard beats hiding the pixels or crashing the render.
    expect(transparencyCode('future_mode')).toBe(TRANSPARENCY_CODE.brush);
  });
});
