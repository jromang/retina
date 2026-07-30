// Geometry of the interactive crop.
//
// Eight handles, one tolerance, fractions to clamp: it all reads as correct and behaves badly at
// the edges. The cases that carry this file are dragging against a border (clamping each edge
// separately squashes the frame instead of stopping it) and the first drag on a frame that is
// still untouched, which must *draw* rather than move the whole image.
//
// Since the process gained its `rotated_rect` mode, the **tilted** frame joins in: the pointer is
// brought back into the rectangle's own axes, and because the stored rectangle turns around its
// own centre, resizing one edge moves that centre — hence the correction the last block locks
// down, opposite edge held still.

import { describe, expect, it } from 'vitest';

import {
  applyDrag,
  cropSize,
  cursorFor,
  frameAngle,
  handlePositions,
  hitTest,
  isFullFrame,
  normalise,
  rectCorners,
  rectPx,
  type CropValues,
} from '../src/viewport/cropTool';

const W = 200;
const H = 100;
/** Frame on the central quarter: (50, 25) → (150, 75) in pixels. */
const FRAME: CropValues = { x0: 0.25, y0: 0.25, x1: 0.75, y1: 0.75, angle: 0 };
const FULL: CropValues = { x0: 0, y0: 0, x1: 1, y1: 1, angle: 0 };
/**
 * The same frame, tilted by a quarter turn: centre (100, 50), so corners at
 * (125, 0) (125, 100) (75, 100) (75, 0). Round numbers, so that an error shows.
 */
const TILTED: CropValues = { ...FRAME, angle: 90, mode: 'rotated_rect' };

/** Point comparison up to rounding — `Math.cos(π/2)` is 6e-17, not 0. */
function expectPoint(actual: readonly [number, number], expected: [number, number]): void {
  expect(actual[0]).toBeCloseTo(expected[0], 6);
  expect(actual[1]).toBeCloseTo(expected[1], 6);
}

describe('normalisation', () => {
  it('puts the edges back in order — dragging upwards flips y', () => {
    expect(normalise({ x0: 0.8, y0: 0.9, x1: 0.2, y1: 0.1, angle: 0 })).toEqual({
      x0: 0.2, y0: 0.1, x1: 0.8, y1: 0.9, angle: 0,
    });
  });

  it('clamps to [0,1]: the process schema accepts nothing else', () => {
    const v = normalise({ x0: -0.5, y0: -2, x1: 1.4, y1: 3, angle: 12 });
    expect([v.x0, v.y0, v.x1, v.y1]).toEqual([0, 0, 1, 1]);
    expect(v.angle).toBe(12);
  });
});

describe('conversion to pixels', () => {
  it('returns the image rectangle', () => {
    expect(rectPx(FRAME, W, H)).toEqual([50, 25, 150, 75]);
  });

  it('gives the dimensions the panel displays', () => {
    expect(cropSize(FRAME, W, H)).toEqual([100, 50]);
  });

  it('recognises the default frame, which covers everything', () => {
    expect(isFullFrame(FULL)).toBe(true);
    expect(isFullFrame(FRAME)).toBe(false);
  });
});

describe('hit-testing', () => {
  it('finds the eight handles where they belong', () => {
    const rect = rectPx(FRAME, W, H);
    for (const [name, [x, y]] of Object.entries(handlePositions(rect))) {
      expect(hitTest(FRAME, [x, y], W, H, 6)).toBe(name);
    }
  });

  it('prefers the nearest handle when two overlap', () => {
    // On a narrow frame, `n` and `nw` sit a few pixels apart: aiming near the corner must
    // resize diagonally, not in height alone.
    const narrow: CropValues = { x0: 0.25, y0: 0.25, x1: 0.3, y1: 0.75, angle: 0 };
    const rect = rectPx(narrow, W, H);
    expect(hitTest(narrow, [rect[0] + 0.5, rect[1]], W, H, 20)).toBe('nw');
  });

  it('moves when grabbing inside a frame that is already drawn', () => {
    expect(hitTest(FRAME, [100, 50], W, H, 6)).toBe('move');
  });

  it('draws on the first drag over a still untouched frame', () => {
    // Otherwise the natural gesture — click in the image and pull — would move a frame that
    // already covers everything, so nothing visible would happen.
    expect(hitTest(FULL, [100, 50], W, H, 6)).toBe('new');
  });

  it('grabs nothing outside the frame', () => {
    expect(hitTest(FRAME, [10, 10], W, H, 6)).toBeNull();
  });

  it('takes its tolerance in image pixels, so the caller derives it from the zoom', () => {
    // 8 px from the corner: outside the tolerance we grab the interior (so we move), within it
    // we resize. At high magnification the caller shrinks the tolerance, and those 8 image
    // pixels would then span a screen distance far too large to aim at a corner.
    expect(hitTest(FRAME, [58, 25], W, H, 6)).toBe('move');
    expect(hitTest(FRAME, [58, 25], W, H, 12)).toBe('nw');
  });
});

describe('drags', () => {
  it('draws a new frame from the starting point', () => {
    const v = applyDrag('new', FULL, [40, 20], [120, 80], W, H);
    expect(rectPx(v, W, H)).toEqual([40, 20, 120, 80]);
  });

  it('draws correctly backwards (up and to the left)', () => {
    const v = applyDrag('new', FULL, [120, 80], [40, 20], W, H);
    expect(rectPx(v, W, H)).toEqual([40, 20, 120, 80]);
  });

  it('moves the frame without deforming it', () => {
    const v = applyDrag('move', FRAME, [100, 50], [120, 60], W, H);
    expect(rectPx(v, W, H)).toEqual([70, 35, 170, 85]);
  });

  it('STOPS the frame against the border instead of squashing it there', () => {
    // The trap: clamping x0 and x1 independently would give [0, …, 150] — a frame widened by
    // force, when the user only meant to push it to the left.
    const v = applyDrag('move', FRAME, [100, 50], [-500, 50], W, H);
    expect(cropSize(v, W, H)).toEqual([100, 50]);
    expect(rectPx(v, W, H)).toEqual([0, 25, 100, 75]);
  });

  it('resizes from a corner', () => {
    const v = applyDrag('se', FRAME, [150, 75], [190, 95], W, H);
    expect(rectPx(v, W, H)).toEqual([50, 25, 190, 95]);
  });

  it('resizes from an edge without touching the other axis', () => {
    const v = applyDrag('w', FRAME, [50, 50], [20, 90], W, H);
    expect(rectPx(v, W, H)).toEqual([20, 25, 150, 75]);
  });

  it('copes with pulling an edge past the opposite one', () => {
    const v = applyDrag('w', FRAME, [50, 50], [180, 50], W, H);
    expect(rectPx(v, W, H)).toEqual([150, 25, 180, 75]);
  });

  it('recomputes from the state the gesture started in, without accumulating', () => {
    // `values` is the state at the start of the drag: replaying the same gesture must give the
    // same result, otherwise a hundred mouse events would make the frame drift.
    const first = applyDrag('se', FRAME, [150, 75], [170, 85], W, H);
    const second = applyDrag('se', FRAME, [150, 75], [170, 85], W, H);
    expect(first).toEqual(second);
  });
});

describe('rotation', () => {
  it('0° when the handle stays above the centre', () => {
    const rect = rectPx(FRAME, W, H);
    const [hx, hy] = handlePositions(rect).rotate;
    expect(applyDrag('rotate', FRAME, [hx, hy], [hx, hy], W, H).angle).toBeCloseTo(0, 6);
  });

  it('pulling the handle RIGHT asks the core for −90°', () => {
    // The sign is not a free convention: `scipy.ndimage.rotate`, which `DynamicCrop._apply`
    // calls, turns the content **anticlockwise** for a positive angle (measured, and locked
    // down by tests/test_dynamic_tools.py). For the image to turn the way the gesture goes, a
    // clockwise drag must therefore produce a negative angle.
    expect(applyDrag('rotate', FRAME, [100, 10], [160, 50], W, H).angle).toBeCloseTo(-90, 6);
    expect(applyDrag('rotate', FRAME, [100, 10], [40, 50], W, H).angle).toBeCloseTo(90, 6);
  });

  it('180° when pulling below the centre', () => {
    expect(Math.abs(applyDrag('rotate', FRAME, [100, 10], [100, 90], W, H).angle)).toBeCloseTo(180, 6);
  });

  it('leaves the frame alone', () => {
    const v = applyDrag('rotate', FRAME, [100, 10], [160, 50], W, H);
    expect(rectPx(v, W, H)).toEqual(rectPx(FRAME, W, H));
  });
});

describe('tilted frame (rotated_rect mode)', () => {
  it('tilts the frame only in the mode that cuts out a tilted rectangle', () => {
    // One angle, two meanings: under `after_crop` it describes a rotation applied after the
    // cut, which the frame must on no account show — showing it would promise one geometry
    // and deliver another.
    expect(frameAngle({ ...FRAME, angle: 90 })).toBe(0);
    expect(frameAngle(TILTED)).toBe(90);
    expectPoint(rectCorners({ ...FRAME, angle: 90 }, W, H)[0], [50, 25]);
  });

  it('places the four corners around the centre', () => {
    const corners = rectCorners(TILTED, W, H);
    expectPoint(corners[0], [125, 0]);
    expectPoint(corners[1], [125, 100]);
    expectPoint(corners[2], [75, 100]);
    expectPoint(corners[3], [75, 0]);
  });

  it('finds the handles at their rotated positions', () => {
    const positions = handlePositions(rectPx(TILTED, W, H), 90);
    for (const [name, point] of Object.entries(positions)) {
      expect(hitTest(TILTED, point, W, H, 6)).toBe(name);
    }
    expectPoint(positions.nw, [125, 0]);
  });

  it('tests containment against the ROTATED frame, not its stored rectangle', () => {
    // (110, 10) lies outside the axis-aligned rectangle (y < 25) but inside the tilted frame;
    // (60, 50) is the other way round. That is the whole point of un-rotating the pointer.
    expect(hitTest(TILTED, [110, 10], W, H, 6)).toBe('move');
    expect(hitTest(TILTED, [60, 50], W, H, 6)).toBeNull();
  });

  it('moves the tilted frame as one block', () => {
    const [a0, a1, a2, a3] = rectCorners(TILTED, W, H);
    const moved = applyDrag('move', TILTED, [100, 50], [110, 60], W, H);
    const [b0, b1, b2, b3] = rectCorners(moved, W, H);
    expectPoint(b0, [a0[0] + 10, a0[1] + 10]);
    expectPoint(b1, [a1[0] + 10, a1[1] + 10]);
    expectPoint(b2, [a2[0] + 10, a2[1] + 10]);
    expectPoint(b3, [a3[0] + 10, a3[1] + 10]);
  });

  it("resizes in the frame's own axes, without drifting the opposite edge", () => {
    // At 90°, the frame's "east" handle points DOWN in the image: pulling it 20 px downwards
    // must lengthen the frame by 20 px. The trap lies elsewhere — the stored rectangle turns
    // around ITS centre, and lengthening x1 moves that centre along the image's x axis, which
    // would shift the west edge the user never touched.
    const v = applyDrag('e', TILTED, [125, 100], [125, 120], W, H);
    const corners = rectCorners(v, W, H);
    const before = rectCorners(TILTED, W, H);
    expectPoint(corners[0], before[0]);         // nw: still
    expectPoint(corners[3], before[3]);         // sw: still
    expectPoint(corners[1], [125, 120]);        // ne: follows the pointer
    expectPoint(corners[2], [75, 120]);
    expect(cropSize(v, W, H)).toEqual([120, 50]);
  });

  it('replays a drag identically — no accumulation', () => {
    expect(applyDrag('e', TILTED, [125, 100], [125, 120], W, H)).toEqual(
      applyDrag('e', TILTED, [125, 100], [125, 120], W, H),
    );
  });

  it('makes the rotation handle follow the pointer, hence a sign that depends on the mode', () => {
    // The tilted frame IS the region being read: it must turn the way the mouse goes, or else
    // gesture and drawing pull against each other. The content will turn the other way — that
    // is what tilting a frame over a photograph does, and the core holds that convention.
    const gesture = { from: [100, 10] as const, to: [160, 50] as const };
    expect(applyDrag('rotate', TILTED, gesture.from, gesture.to, W, H).angle).toBeCloseTo(90, 6);
    expect(applyDrag('rotate', FRAME, gesture.from, gesture.to, W, H).angle).toBeCloseTo(-90, 6);
  });

  it('always draws an axis-aligned frame, even when an angle is already set', () => {
    // There is no guessing which edge of a tilted rectangle a drag describes: drawing lays down
    // the geometry, and the handle tilts it afterwards.
    const v = applyDrag('new', { ...FULL, angle: 30, mode: 'rotated_rect' }, [40, 20], [120, 80], W, H);
    expect(rectPx(v, W, H)).toEqual([40, 20, 120, 80]);
    expect(v.angle).toBe(30);
    expect(v.mode).toBe('rotated_rect');
  });
});

describe('cursors', () => {
  it('maps each handle to the expected resize cursor', () => {
    expect(cursorFor('nw')).toBe('nwse-resize');
    expect(cursorFor('ne')).toBe('nesw-resize');
    expect(cursorFor('n')).toBe('ns-resize');
    expect(cursorFor('e')).toBe('ew-resize');
    expect(cursorFor('move')).toBe('move');
    expect(cursorFor(null)).toBe('crosshair');
  });
});
