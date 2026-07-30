// Geometry of interactive cropping — pure logic, without canvas or DOM.
//
// Extracted from the panel so as to be testable in vitest, like `overlay.ts::viewAt`: hit-testing
// eight handles under a pixel tolerance is exactly the kind of code one believes
// correct just by reading it.
//
// # Two semantics for a single angle — and therefore two frames
//
// The core (`processes/retouch.py`) now knows how to do both, selected by its `mode` enum:
//
// - `after_crop` (the default, the historical one) crops the **axis-aligned** rectangle then
//   rotates the result. The frame therefore stays aligned and the rotation is shown by a separate
//   arm, which announces what will happen *after* the crop: tilting it would promise the
//   rotated-rectangle behavior and deliver ours.
// - `rotated_rect` samples the **tilted** rectangle itself. There, the
//   reason not to tilt the frame disappears: the drawn frame *is* the region read, and its
//   size is that of the output. It is this mode that rotates all the geometry below.
//
// A consequence on signs, counter-intuitive but physical: tilting the frame clockwise
// yields content rotated counter-clockwise (the frame turns *on* the photo). Hence
// `applyDrag('rotate')`, which negates the gesture's angle in `after_crop` — where the user aims
// at the content — and not in `rotated_rect`, where they aim at the frame.

/** Semantics of the angle — exact mirror of the process's `mode` enum. */
export type CropMode = 'after_crop' | 'rotated_rect';

/** Values of the process: fractions [0,1] of the target view, plus the angle in degrees. */
export interface CropValues {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  angle: number;
  /** Absent = `after_crop`, as in recipes and icons saved before this parameter existed. */
  mode?: CropMode | undefined;
}

export type Handle =
  | 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w'
  | 'move'
  | 'rotate'
  /** No useful frame laid down yet: the drag draws a new one. */
  | 'new';

/** Rectangle in image pixels: (x0, y0, x1, y1), normalized (x0 ≤ x1). */
export type RectPx = [number, number, number, number];

/** Point in image pixels. */
export type Point = [number, number];

const clamp01 = (v: number) => Math.min(Math.max(v, 0), 1);

/** Puts the fractions back in order and within [0,1] — the process's schema requires it. */
export function normalise(values: CropValues): CropValues {
  const x0 = clamp01(Math.min(values.x0, values.x1));
  const x1 = clamp01(Math.max(values.x0, values.x1));
  const y0 = clamp01(Math.min(values.y0, values.y1));
  const y1 = clamp01(Math.max(values.y0, values.y1));
  return { x0, y0, x1, y1, angle: values.angle, mode: values.mode };
}

export function rectPx(values: CropValues, width: number, height: number): RectPx {
  const v = normalise(values);
  return [v.x0 * width, v.y0 * height, v.x1 * width, v.y1 * height];
}

/**
 * Tilt **of the frame**, in degrees: zero as long as the mode does not tilt it.
 *
 * `angle` is still carried by the values in both modes — it is the same process parameter —
 * but in `after_crop` it describes a rotation posterior to the crop, which the rectangle must
 * not show. All the rest of the file goes through here rather than through `values.angle`.
 */
export function frameAngle(values: CropValues): number {
  return values.mode === 'rotated_rect' ? values.angle : 0;
}

/** Center of the rectangle in image pixels — the pivot, here as in `DynamicCrop._sample_rotated`. */
function centreOf(rect: RectPx): Point {
  return [(rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2];
}

/**
 * Rotates `point` by `deg` around `centre`, in the image frame (y downwards).
 *
 * Standard matrix `[[cos, −sin], [sin, cos]]`: the same as the core's, which sends the rectangle's
 * +u axis onto `(cos, sin)`. Since the y axis points down, this *looks* clockwise on screen; and
 * because the camera is only a scaling (no rotation, see `camera.ts`), the image angle
 * carries over as is into a `ctx.rotate`, which turns in the same direction.
 */
export function rotateAround(
  point: readonly [number, number],
  centre: readonly [number, number],
  deg: number,
): Point {
  if (deg === 0) return [point[0], point[1]];
  const a = (deg * Math.PI) / 180;
  const cos = Math.cos(a);
  const sin = Math.sin(a);
  const dx = point[0] - centre[0];
  const dy = point[1] - centre[1];
  return [centre[0] + cos * dx - sin * dy, centre[1] + sin * dx + cos * dy];
}

/**
 * The four corners (nw, ne, se, sw) in image pixels, tilted if the mode requires it.
 *
 * The type is a **quadruplet** and not an array: the caller reads `corners[0]` to anchor
 * the angle label there, and an array would force it to handle a "no fourth corner" case
 * that cannot exist.
 */
export function rectCorners(
  values: CropValues,
  width: number,
  height: number,
): [Point, Point, Point, Point] {
  const rect = rectPx(values, width, height);
  const centre = centreOf(rect);
  const tilt = frameAngle(values);
  return [
    rotateAround([rect[0], rect[1]], centre, tilt),
    rotateAround([rect[2], rect[1]], centre, tilt),
    rotateAround([rect[2], rect[3]], centre, tilt),
    rotateAround([rect[0], rect[3]], centre, tilt),
  ];
}

/** True if the frame covers (almost) the whole image — the process's default state. */
export function isFullFrame(values: CropValues, epsilon = 1e-6): boolean {
  const v = normalise(values);
  return v.x0 <= epsilon && v.y0 <= epsilon && v.x1 >= 1 - epsilon && v.y1 >= 1 - epsilon;
}

/**
 * Length of the rotation arm, in image pixels.
 *
 * Proportional to the frame's height so as to stay visible on a large crop as on a small
 * one, but bounded from below: on a ten-pixel frame, a fraction would be within
 * the thickness of the stroke.
 */
export function armLength(rect: RectPx): number {
  return Math.max(14, (rect[3] - rect[1]) * 0.18);
}

/**
 * Positions of the handles in image pixels.
 *
 * `angleDeg` rotates the whole set around the center — that is what gives the handles of the
 * tilted frame. Without an argument, the function returns the positions **in the local frame**:
 * hit-testing needs them unrotated, since it brings the pointer back into that frame.
 */
export function handlePositions(
  rect: RectPx,
  angleDeg = 0,
): Record<Exclude<Handle, 'move' | 'new'>, Point> {
  const [x0, y0, x1, y1] = rect;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  const base: Record<Exclude<Handle, 'move' | 'new'>, Point> = {
    nw: [x0, y0], n: [cx, y0], ne: [x1, y0],
    w: [x0, cy], e: [x1, cy],
    sw: [x0, y1], s: [cx, y1], se: [x1, y1],
    rotate: [cx, y0 - armLength(rect)],
  };
  if (angleDeg === 0) return base;
  const centre: Point = [cx, cy];
  for (const name of Object.keys(base) as (keyof typeof base)[]) {
    base[name] = rotateAround(base[name], centre, angleDeg);
  }
  return base;
}

/**
 * Handle under the point, or `move` / `new` / `null`.
 *
 * `tolerance` is in **image** pixels: the caller derives it from the zoom, so that a handle stays
 * grabbable on screen whatever the scale (otherwise, at 1:8, one would have to aim to an eighth
 * of a pixel).
 *
 * Tilted frame: the pointer is brought back into the rectangle's frame by the inverse rotation
 * about the center, and all the rest is the axis-aligned logic, unchanged. Since a rotation
 * is an isometry, the tolerance keeps its meaning in both frames.
 */
export function hitTest(
  values: CropValues,
  point: readonly [number, number],
  width: number,
  height: number,
  tolerance: number,
): Handle | null {
  const rect = rectPx(values, width, height);
  const [px, py] = rotateAround(point, centreOf(rect), -frameAngle(values));

  // The handles first: on a tiny frame they overlap, and the user wants
  // to resize rather than move.
  const positions = handlePositions(rect);
  let best: Handle | null = null;
  let bestDistance = tolerance;
  for (const [name, [hx, hy]] of Object.entries(positions)) {
    const distance = Math.hypot(px - hx, py - hy);
    if (distance <= bestDistance) {
      bestDistance = distance;
      best = name as Handle;
    }
  }
  if (best) return best;

  const inside = px >= rect[0] && px <= rect[2] && py >= rect[1] && py <= rect[3];
  if (!inside) return null;
  // Frame still pristine: the first drag must *draw*, not move the whole image.
  return isFullFrame(values) ? 'new' : 'move';
}

/**
 * New values after a drag from `from` to `to` (image points).
 *
 * `values` is the state at the **start** of the gesture: recomputing from the origin rather than
 * accumulating the deltas avoids rounding drift over a drag of several hundred events.
 */
export function applyDrag(
  handle: Handle,
  values: CropValues,
  from: readonly [number, number],
  to: readonly [number, number],
  width: number,
  height: number,
): CropValues {
  if (width <= 0 || height <= 0) return values;
  const v = normalise(values);
  const rect = rectPx(v, width, height);
  const centre = centreOf(rect);
  const tilt = frameAngle(v);

  if (handle === 'new') {
    // A frame is always **drawn** axis-aligned: the tilt is set afterwards, at the handle. The
    // opposite would force us to guess which edge of the tilted rectangle the drag describes.
    return normalise({
      x0: from[0] / width, y0: from[1] / height,
      x1: to[0] / width, y1: to[1] / height,
      angle: v.angle, mode: v.mode,
    });
  }

  if (handle === 'move') {
    // Movement is **bounded**, not clamped independently on each edge: clamping x0 and x1
    // separately would squash the frame against the border instead of stopping it there.
    // The movement reads in image coordinates even when tilted: since the rotation has the center
    // as its pivot, translating the center translates the rotated frame identically.
    const dx = (to[0] - from[0]) / width;
    const dy = (to[1] - from[1]) / height;
    const shift = Math.min(Math.max(dx, -v.x0), 1 - v.x1);
    const rise = Math.min(Math.max(dy, -v.y0), 1 - v.y1);
    return {
      x0: v.x0 + shift, y0: v.y0 + rise, x1: v.x1 + shift, y1: v.y1 + rise,
      angle: v.angle, mode: v.mode,
    };
  }

  if (handle === 'rotate') {
    // Angle measured from the vertical — the handle points upwards, hence 0° at rest.
    const raw = (Math.atan2(to[0] - centre[0], -(to[1] - centre[1])) * 180) / Math.PI;
    // The sign is not deduced, it is measured (tests/test_dynamic_tools.py locks the
    // core's convention, shared by both modes): a positive angle rotates the **content**
    // counter-clockwise, and tilts the **frame** clockwise.
    //   - `after_crop`: the handle announces the rotation of the content, so a clockwise gesture
    //     must give a negative angle. Without this negation, the image would go opposite the gesture.
    //   - `rotated_rect`: the handle carries the frame, which must follow the pointer — the sign is
    //     then the gesture's. The content rotates the other way, which is the nature of a frame
    //     one tilts on a photo.
    const angle = v.mode === 'rotated_rect' ? raw : -raw;
    return { ...v, angle: Math.round(angle * 10) / 10 };
  }

  // Edge handles: the drag reads in the frame's **own** coordinate system. Pulling the "east"
  // handle of a tilted frame must widen it towards its own right, not towards the image's east.
  const fromLocal = rotateAround(from, centre, -tilt);
  const toLocal = rotateAround(to, centre, -tilt);
  const dx = (toLocal[0] - fromLocal[0]) / width;
  const dy = (toLocal[1] - fromLocal[1]) / height;
  const next = { ...v };
  if (handle.includes('n')) next.y0 = clamp01(v.y0 + dy);
  if (handle.includes('s')) next.y1 = clamp01(v.y1 + dy);
  if (handle.includes('w')) next.x0 = clamp01(v.x0 + dx);
  if (handle.includes('e')) next.x1 = clamp01(v.x1 + dx);
  const resized = normalise(next);
  if (tilt === 0) return resized;

  // The stored rectangle is axis-aligned and turns around **its** center: moving an edge shifts
  // that center along the image's axes, whereas the gesture moved it along the frame's
  // axes. Without this correction, the opposite edge — which the user does not touch — would drift
  // on screen. So we put the center back where the local frame expects it.
  const moved = centreOf(rectPx(resized, width, height));
  const wanted = rotateAround(moved, centre, tilt);
  const sx = (wanted[0] - moved[0]) / width;
  const sy = (wanted[1] - moved[1]) / height;
  // `normalise` bounds within [0,1], the domain of the parameters: a tilted frame pushed outside
  // the image loses a little size there, but no illegal value reaches the process.
  return normalise({
    ...resized,
    x0: resized.x0 + sx, x1: resized.x1 + sx,
    y0: resized.y0 + sy, y1: resized.y1 + sy,
  });
}

/** CSS cursor of a handle — the same convention as the window resizes. */
export function cursorFor(handle: Handle | null): string {
  switch (handle) {
    case 'nw': case 'se': return 'nwse-resize';
    case 'ne': case 'sw': return 'nesw-resize';
    case 'n': case 's': return 'ns-resize';
    case 'e': case 'w': return 'ew-resize';
    case 'move': return 'move';
    case 'rotate': return 'grab';
    default: return 'crosshair';
  }
}

/** Dimensions in pixels of the current rectangle — what the panel shows the user. */
export function cropSize(values: CropValues, width: number, height: number): [number, number] {
  const rect = rectPx(values, width, height);
  return [Math.round(rect[2] - rect[0]), Math.round(rect[3] - rect[1])];
}
