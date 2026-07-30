// Vector drawing layer on top of the WebGL viewport.
//
// A separate 2D canvas rather than GL primitives: previews, drop outline and magnifier are
// interface graphics, not image pixels. Mixing them into the render would force a
// re-upload or a redraw of the texture on every hover, whereas they change a hundred times
// more often than the image.

import type { OverlayItem, ViewState } from '../api/types';
import type { Camera } from './camera';

/** Rectangle in image coordinates: (x0, y0, x1, y1). */
export type Rect = [number, number, number, number];

export interface DropTarget {
  /** Targeted view — preview or main view. */
  viewId: string;
  /** `null` = the whole image. */
  rect: Rect | null;
  legal: boolean;
}

export interface OverlayContent {
  views: readonly ViewState[];
  activeViewId: string | null;
  drop: DropTarget | null;
  /** Frame currently being drawn (new preview or move). */
  rubber: Rect | null;
  /** Magnifier active: we draw its frame, the content comes from a second GL render. */
  loupe: { size: number } | null;
  /** Overlays laid down by the domain (`app.add_overlay`) — hence from the console too. */
  overlays?: readonly OverlayItem[];
  /**
   * Transient drawing of the active dynamic tool — handles, radius circle, line in progress.
   *
   * Stays **client-side**, unlike the overlays: it changes on every mouse
   * move, and one RPC round trip per frame would drown the console in echoes. Only the
   * *committed* state of a gesture goes back up to the domain.
   */
  chrome?: ((ctx: CanvasRenderingContext2D, camera: Camera) => void) | null;
}

function token(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** Domain RGBA (0..1) → CSS color. An overlay without a color gets the default one. */
function cssColor(color: readonly number[] | undefined, fallback: string): string {
  if (!color || color.length < 3) return fallback;
  const [r, g, b, a = 1] = color;
  const to255 = (v: number) => Math.round(Math.min(Math.max(v, 0), 1) * 255);
  return `rgba(${to255(r!)}, ${to255(g!)}, ${to255(b!)}, ${Math.min(Math.max(a, 0), 1)})`;
}

const OVERLAY_DEFAULT = 'rgba(255, 212, 121, 0.95)';

/**
 * Draws the domain's overlays.
 *
 * Every type tolerates missing data: the domain validates only the `kind`, and a
 * script that lays down an incomplete overlay must not take the rest of the layer (preview
 * frames, drop outline) down with it.
 */
function drawDomainOverlays(
  ctx: CanvasRenderingContext2D,
  camera: Camera,
  overlays: readonly OverlayItem[],
): void {
  const toScreen = (x: number, y: number): readonly [number, number] =>
    camera.imageToViewport([x, y]);

  for (const overlay of overlays) {
    ctx.save();
    const color = cssColor(overlay.color, OVERLAY_DEFAULT);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = overlay.width ?? 1.5;

    if (overlay.kind === 'markers') {
      // A cross rather than a disc: it lets the targeted pixel show through, which is the very
      // point of a sample marker.
      const half = (overlay.size ?? 9) / 2;
      ctx.beginPath();
      for (const point of overlay.points ?? []) {
        const [sx, sy] = toScreen(point[0], point[1]);
        ctx.moveTo(sx - half, sy);
        ctx.lineTo(sx + half, sy);
        ctx.moveTo(sx, sy - half);
        ctx.lineTo(sx, sy + half);
      }
      ctx.stroke();
    } else if (overlay.kind === 'lines') {
      const polylines = overlay.segments ?? (overlay.points ? [overlay.points] : []);
      ctx.beginPath();
      for (const line of polylines) {
        line.forEach((point, index) => {
          const [sx, sy] = toScreen(point[0], point[1]);
          if (index === 0) ctx.moveTo(sx, sy);
          else ctx.lineTo(sx, sy);
        });
      }
      ctx.stroke();
    } else if (overlay.kind === 'text') {
      ctx.font = `${overlay.size ?? 12}px var(--retina-font-ui)`;
      for (const item of overlay.items ?? []) {
        const [sx, sy] = toScreen(Number(item['x'] ?? 0), Number(item['y'] ?? 0));
        ctx.fillText(String(item['text'] ?? ''), sx, sy);
      }
    } else if (overlay.kind === 'ellipses') {
      // The radii are in **image** pixels: they must follow the zoom, otherwise a PSF ellipse
      // would only cover its star at a single magnification factor.
      for (const item of overlay.items ?? []) {
        const [sx, sy] = toScreen(Number(item['x'] ?? 0), Number(item['y'] ?? 0));
        const rx = camera.imageScalarToViewport(Number(item['rx'] ?? 0));
        const ry = camera.imageScalarToViewport(Number(item['ry'] ?? 0));
        if (rx <= 0 || ry <= 0) continue;
        ctx.beginPath();
        ctx.ellipse(sx, sy, rx, ry, Number(item['theta'] ?? 0), 0, Math.PI * 2);
        ctx.stroke();
      }
    } else if (overlay.kind === 'rects') {
      const angle = ((overlay.angle ?? 0) * Math.PI) / 180;
      for (const rect of overlay.rects ?? []) {
        const [sx0, sy0] = toScreen(rect[0], rect[1]);
        const [sx1, sy1] = toScreen(rect[2], rect[3]);
        if (angle === 0) {
          ctx.strokeRect(sx0, sy0, sx1 - sx0, sy1 - sy0);
          continue;
        }
        // Rotation about the center, as DynamicCrop rotates the rectangle it cuts out.
        ctx.save();
        ctx.translate((sx0 + sx1) / 2, (sy0 + sy1) / 2);
        ctx.rotate(angle);
        ctx.strokeRect(-(sx1 - sx0) / 2, -(sy1 - sy0) / 2, sx1 - sx0, sy1 - sy0);
        ctx.restore();
      }
    }
    ctx.restore();
  }
}

export function drawOverlay(
  canvas: HTMLCanvasElement,
  camera: Camera,
  content: OverlayContent,
): void {
  const { views, activeViewId, drop, rubber, loupe, overlays, chrome } = content;
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(canvas.clientWidth * dpr));
  const height = Math.max(1, Math.round(canvas.clientHeight * dpr));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);

  const toScreen = (x: number, y: number): readonly [number, number] =>
    camera.imageToViewport([x, y]);

  // --- previews ------------------------------------------------------------
  for (const view of views) {
    if (!view.is_preview || !view.rect) continue;
    const [x0, y0, x1, y1] = view.rect;
    const [sx0, sy0] = toScreen(x0, y0);
    const [sx1, sy1] = toScreen(x1, y1);
    const active = view.id === activeViewId;

    ctx.save();
    // ⚡ volatile dashed, 🔒 frozen solid: the same distinction as in the window
    // tree, readable directly on the image.
    ctx.setLineDash(view.volatile ? [4, 3] : []);
    ctx.lineWidth = active ? 2 : 1;
    ctx.strokeStyle = active
      ? token('--retina-preview-outline', '#ffd479')
      : token('--retina-preview-frozen', '#7ad17a');
    ctx.strokeRect(sx0, sy0, sx1 - sx0, sy1 - sy0);

    if (sx1 - sx0 > 40 && sy1 - sy0 > 16) {
      ctx.setLineDash([]);
      ctx.font = '11px var(--retina-font-mono)';
      ctx.fillStyle = ctx.strokeStyle;
      ctx.fillText(view.id, sx0 + 4, sy0 + 13);
    }
    ctx.restore();
  }

  // --- drop target ---------------------------------------------------------
  if (drop) {
    const rect = drop.rect ?? [0, 0, camera.imageWidth, camera.imageHeight];
    const [sx0, sy0] = toScreen(rect[0], rect[1]);
    const [sx1, sy1] = toScreen(rect[2], rect[3]);

    ctx.save();
    ctx.lineWidth = 3;
    ctx.strokeStyle = drop.legal
      ? token('--retina-drop-legal', '#33e5ff')
      : token('--retina-drop-illegal', '#f14c4c');
    if (!drop.legal) ctx.setLineDash([6, 4]);
    ctx.strokeRect(sx0, sy0, sx1 - sx0, sy1 - sy0);

    // Name of the target, at the top left of the outline: one knows what will be hit before
    // releasing — that is the whole point of the affordance.
    const label = drop.legal ? drop.viewId : 'process global : pas de vue cible';
    ctx.font = '12px var(--retina-font-ui)';
    const padding = 4;
    const textWidth = ctx.measureText(label).width;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
    ctx.fillRect(sx0, Math.max(0, sy0 - 20), textWidth + padding * 2, 18);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fillText(label, sx0 + padding, Math.max(13, sy0 - 6));
    ctx.restore();
  }

  // --- frame currently being drawn -----------------------------------------
  if (rubber) {
    const [sx0, sy0] = toScreen(Math.min(rubber[0], rubber[2]), Math.min(rubber[1], rubber[3]));
    const [sx1, sy1] = toScreen(Math.max(rubber[0], rubber[2]), Math.max(rubber[1], rubber[3]));
    ctx.save();
    ctx.setLineDash([5, 3]);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = token('--retina-preview-outline', '#ffd479');
    ctx.strokeRect(sx0, sy0, sx1 - sx0, sy1 - sy0);
    ctx.setLineDash([]);
    ctx.font = '11px var(--retina-font-mono)';
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fillText(
      `${Math.round(Math.abs(rubber[2] - rubber[0]))} × ${Math.round(Math.abs(rubber[3] - rubber[1]))}`,
      sx0 + 4,
      sy0 - 4,
    );
    ctx.restore();
  }

  // --- domain overlays, then chrome of the active tool ---------------------
  // After the preview frames and before the magnifier: these are annotations of the image, so
  // they must pass over the cropping guides but stay under the magnifier.
  if (overlays && overlays.length > 0) drawDomainOverlays(ctx, camera, overlays);
  if (chrome) {
    ctx.save();
    chrome(ctx, camera);
    ctx.restore();
  }

  // --- frame of the magnifier ----------------------------------------------
  if (loupe) {
    // The content is painted by a second GL render (see renderer.renderLoupe); here we draw
    // only the frame and the cross, which have no business being in the shader.
    const size = loupe.size;
    const x = canvas.clientWidth - size - 8;
    const y = 8;
    ctx.save();
    ctx.strokeStyle = token('--retina-loupe-ring', '#888888');
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, size, size);
    ctx.strokeStyle = 'rgba(255, 60, 60, 0.9)';
    ctx.beginPath();
    ctx.moveTo(x + size / 2, y + size / 2 - 6);
    ctx.lineTo(x + size / 2, y + size / 2 + 6);
    ctx.moveTo(x + size / 2 - 6, y + size / 2);
    ctx.lineTo(x + size / 2 + 6, y + size / 2);
    ctx.stroke();
    ctx.restore();
  }
}

/**
 * View targeted by an image point: the **smallest** preview that contains it, otherwise the main
 * view. Same rule as ``gui/dnd.py::_target_at`` — without which a nested preview
 * would be unreachable.
 */
export function viewAt(
  views: readonly ViewState[],
  mainViewId: string,
  x: number,
  y: number,
): { viewId: string; rect: Rect | null } {
  let best: ViewState | null = null;
  let bestArea = Infinity;

  for (const view of views) {
    if (!view.is_preview || !view.rect) continue;
    const [x0, y0, x1, y1] = view.rect;
    if (x < x0 || x > x1 || y < y0 || y > y1) continue;
    const area = (x1 - x0) * (y1 - y0);
    if (area < bestArea) {
      bestArea = area;
      best = view;
    }
  }

  if (best?.rect) return { viewId: best.id, rect: best.rect };
  return { viewId: mainViewId, rect: null };
}
