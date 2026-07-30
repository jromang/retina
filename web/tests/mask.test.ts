// On-screen mask compositing: the semantics must be the domain's.
//
// The reference is `Process.execute_on` (python/retina/process/base.py):
//
//     processed = original * (1 - m) + processed * m
//
// so **white = processed, black = protected**, and that is locked down on the Python side by
// tests/test_mask.py. The display must say the same thing, otherwise the user would protect
// the opposite of what they think. What we test here are the CPU functions written to match the
// GLSL exactly — the shader itself is checked by the Playwright scenario, which reads the
// framebuffer back.

import { describe, expect, it, vi } from 'vitest';

import {
  MASK_MODE_CODE,
  MASK_OVERLAY_COLORS,
  composeMaskDisplay,
  effectiveMaskValue,
  maskCompositing,
  maskUvTransform,
} from '../src/viewport/shaders';

const IMAGE: readonly [number, number, number] = [0.8, 0.6, 0.4];

describe('effective mask weight', () => {
  it('reads the red channel alone on a mono mask', () => {
    // R16F: the texture returns (r, 0, 0, 1). Averaging the three would give r/3 — a mask three
    // times too protective, and the mistake would pass for a contrast setting.
    expect(effectiveMaskValue([0.6, 0, 0], true, false)).toBeCloseTo(0.6, 6);
  });

  it('averages the channels of a color mask, like mask_array', () => {
    expect(effectiveMaskValue([0.9, 0.6, 0.3], false, false)).toBeCloseTo(0.6, 6);
  });

  it('inverts on the display side, without re-uploading the texture', () => {
    expect(effectiveMaskValue([0.25, 0, 0], true, true)).toBeCloseTo(0.75, 6);
  });

  it('clamps values outside [0, 1] (a mask may leave the range)', () => {
    expect(effectiveMaskValue([1.4, 0, 0], true, false)).toBe(1);
    expect(effectiveMaskValue([-0.3, 0, 0], true, false)).toBe(0);
  });
});

describe('display modes', () => {
  it('the domain’s ten modes reduce to three ways of compositing', () => {
    expect(maskCompositing('replace').mode).toBe(MASK_MODE_CODE.replace);
    expect(maskCompositing('multiply').mode).toBe(MASK_MODE_CODE.multiply);
    for (const mode of Object.keys(MASK_OVERLAY_COLORS)) {
      expect(maskCompositing(mode).mode).toBe(MASK_MODE_CODE.overlay);
    }
  });

  it('each overlay mode carries its own tint, all distinct', () => {
    const tints = Object.keys(MASK_OVERLAY_COLORS).map((m) => maskCompositing(m).color.join(','));
    expect(new Set(tints).size).toBe(tints.length);
    expect(maskCompositing('overlay_cyan').color).toEqual([0, 1, 1]);
  });

  it('an unknown mode falls back to red, the domain default', () => {
    // A domain newer than the client: showing the mask in an unexpected color beats showing
    // nothing, which would read as "no mask at all".
    const unknown = maskCompositing('overlay_chartreuse');
    expect(unknown.mode).toBe(MASK_MODE_CODE.overlay);
    expect(unknown.color).toEqual([1, 0, 0]);
  });
});

describe('compositing onto the display color', () => {
  it('off mode: the image passes through untouched', () => {
    const off = { mode: MASK_MODE_CODE.off, color: [1, 0, 0] as const };
    expect(composeMaskDisplay(IMAGE, 0.3, off)).toEqual([0.8, 0.6, 0.4]);
  });

  it('replace: you see the weight itself, in gray', () => {
    const replace = maskCompositing('replace');
    expect(composeMaskDisplay(IMAGE, 0.25, replace)).toEqual([0.25, 0.25, 0.25]);
  });

  it('multiply: the protected area goes dark, the processed area stays', () => {
    const multiply = maskCompositing('multiply');
    expect(composeMaskDisplay(IMAGE, 0, multiply)).toEqual([0, 0, 0]);
    expect(composeMaskDisplay(IMAGE, 1, multiply)).toEqual([0.8, 0.6, 0.4]);
  });

  it('overlay: the tint marks what is PROTECTED, not what is processed', () => {
    // The sense that matters. Tinting the processed area would show the exact complement of the
    // truth, and that is the mistake an eyeball test never catches — both images look plausible.
    const red = maskCompositing('overlay_red');
    expect(composeMaskDisplay(IMAGE, 0, red)).toEqual([1, 0, 0]);
    expect(composeMaskDisplay(IMAGE, 1, red)).toEqual([0.8, 0.6, 0.4]);
  });

  it('overlay: an intermediate weight interpolates linearly toward the tint', () => {
    const green = maskCompositing('overlay_green');
    const [r, g, b] = composeMaskDisplay([1, 1, 1], 0.5, green);
    expect(r).toBeCloseTo(0.5, 6);
    expect(g).toBeCloseTo(1, 6);
    expect(b).toBeCloseTo(0.5, 6);
  });

  it('an all-white mask changes NOTHING in the three useful modes', () => {
    // The exact counterpart of test_mask_disabled_has_no_effect: a mask at 1 means everything is
    // processed, so the display must not flag anything.
    for (const mode of ['multiply', 'overlay_red', 'overlay_violet']) {
      expect(composeMaskDisplay(IMAGE, 1, maskCompositing(mode))).toEqual([0.8, 0.6, 0.4]);
    }
  });
});

describe('coverage of the modes offered to the user', () => {
  // `api/client.ts` reads the URL and sessionStorage when the module loads; commands.ts depends
  // on it transitively. Same stub as menus.test.ts.
  vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
  vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

  it('the label table covers exactly the domain’s ten modes', async () => {
    // Two tables describe the modes: the tints (shaders.ts, for the GPU) and the labels
    // (commands.ts, for humans). Adding a mode on one side only would give either a menu entry
    // with no color, or a color no menu offers.
    const { MASK_DISPLAY_MODES } = await import('../src/shell/commands');
    const offered = new Set(MASK_DISPLAY_MODES.map(([mode]) => mode));
    const expected = new Set([...Object.keys(MASK_OVERLAY_COLORS), 'replace', 'multiply']);
    expect(offered).toEqual(expected);
  });
});

describe('mask texture window', () => {
  it('main view: the mask covers the texture exactly', () => {
    expect(maskUvTransform(undefined, 100, 50)).toEqual([0, 0, 1, 1]);
  });

  it('preview: the uv window narrows to the preview rectangle', () => {
    // Otherwise the whole mask would be squeezed into the preview — plausible to the eye, wrong.
    expect(maskUvTransform([25, 10, 75, 30], 100, 50)).toEqual([0.25, 0.2, 0.5, 0.4]);
  });

  it('a bottom-right preview does read the bottom-right corner of the mask', () => {
    const [ox, oy, sx, sy] = maskUvTransform([50, 25, 100, 50], 100, 50);
    expect([ox + sx, oy + sy]).toEqual([1, 1]);
  });

  it('absurd window geometry falls back to identity rather than dividing by zero', () => {
    expect(maskUvTransform([0, 0, 10, 10], 0, 0)).toEqual([0, 0, 1, 1]);
  });
});
