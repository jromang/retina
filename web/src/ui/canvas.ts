// 2D drawing utilities — the plumbing common to the project's plots.
//
// Three canvases exist today (STF histogram, curve editor, selector metrics) and all three
// repeated the same twenty lines: read a theme CSS variable, resize the bitmap according to the
// `devicePixelRatio`, set the transform. Repeated, that plumbing diverges — which already
// happened between `StfPanel` and `CurveEditor`, which did not size their canvas the same way.
//
// Deliberately tiny: this is not a charting library. The project embeds none and needs none —
// a scatter plot and a curve are drawn in ten lines of 2D canvas, where a dependency would cost
// its weight on every load.

/** Value of a theme CSS variable, with a fallback if the theme does not define it. */
export function token(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export interface Surface {
  ctx: CanvasRenderingContext2D;
  /** Dimensions in **CSS** pixels — the units one reasons in while drawing. */
  width: number;
  height: number;
}

/**
 * Prepares a canvas for crisp drawing on a HiDPI screen, and returns its context.
 *
 * The bitmap is sized in **physical** pixels (`clientWidth × dpr`) while the transform brings
 * the drawing frame back to CSS pixels: one therefore draws in layout units, without having to
 * multiply every coordinate. Without this, a 2× screen renders blurry strokes — the classic
 * canvas mistake.
 *
 * Returns `null` if the 2D context is not available (canvas detached from the document).
 */
export function prepare(canvas: HTMLCanvasElement, height: number): Surface | null {
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const bitmapWidth = Math.max(1, Math.round(width * dpr));
  const bitmapHeight = Math.max(1, Math.round(height * dpr));
  // Reassigning `width`/`height` clears the canvas: do it only when the size actually moved,
  // otherwise a redraw at constant size would start from a needlessly reset state.
  if (canvas.width !== bitmapWidth || canvas.height !== bitmapHeight) {
    canvas.width = bitmapWidth;
    canvas.height = bitmapHeight;
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { ctx, width, height };
}

/** Fills the background with the theme's editor color — the starting point of all three plots. */
export function fillBackground(surface: Surface): void {
  surface.ctx.fillStyle = token('--vscode-editor-background', '#1e1e1e');
  surface.ctx.fillRect(0, 0, surface.width, surface.height);
}

/**
 * Maps a value from one range to another.
 *
 * A degenerate source range (min = max) would give a division by zero: the middle of the target
 * is returned instead, which centers a perfectly homogeneous batch rather than making it
 * disappear off frame.
 */
export function scale(
  value: number,
  from: [number, number],
  to: [number, number],
): number {
  const span = from[1] - from[0];
  if (Math.abs(span) < 1e-12) return (to[0] + to[1]) / 2;
  return to[0] + ((value - from[0]) / span) * (to[1] - to[0]);
}
