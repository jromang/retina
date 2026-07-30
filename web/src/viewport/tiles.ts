// Tiling of large images — the pure logic (levels, visible tiles, keys, UV).
//
// An image with a side larger than `MAX_TEXTURE_SIZE` cannot become ONE texture: it
// becomes a **lazy pyramid** served by `/api/pixels?scale=&rect=`:
//   - an **overview** (coarsest level, side ≤ OVERVIEW_MAX), a single texture
//     always resident — the universal fallback drawn under the tiles, no pixel is
//     ever black during the fetches;
//   - **tiles** at the level chosen by the zoom (`scaleForZoom`), fetched on demand
//     for the visible region. The cost is bounded to ~4× the viewport whatever the zoom.
// The dimensions of a level are `ceil(dim / scale)` — a formula shared with the server
// (`server/pixels.py::_to_f16_level`, identical per-octave cascade of ceils).

/** Side of a tile, in LEVEL pixels. 2048: large enough for few calls, small enough
 *  that fetching one tile (24 MB in f16 color) stays responsive while panning. */
export const TILE_SIZE = 2048;

/** Maximum side of the overview. Not `maxTextureSize`: 16384²×3 in f16 would be 1.6 GB pinned —
 *  4096 (75 MB) is enough to cover the screen when zoomed out. */
export const OVERVIEW_MAX = 4096;

/** Server guard rail (`MAX_SCALE`): beyond it, `?scale=` answers 400. */
export const MAX_SERVER_SCALE = 256;

/** Debug override: forces an artificially low texture cap so that tiling can be tested
 *  with a small image (e2e). Read HERE only — definitely not in `caps`: clamping
 *  `maxTextureSize` would break `ensureSize` of the hidden GL canvas. */
export const TEXTURE_CAP_DEBUG_KEY = 'retina.debug.textureCap';

export function tileCap(maxTextureSize: number): number {
  try {
    const raw = globalThis.localStorage?.getItem(TEXTURE_CAP_DEBUG_KEY);
    if (raw) {
      const forced = Number(raw);
      if (Number.isFinite(forced) && forced >= 64) return Math.min(forced, maxTextureSize);
    }
  } catch {
    // localStorage unreachable (tests, iframe sandbox): the real cap prevails
  }
  return maxTextureSize;
}

export function needsTiling(width: number, height: number, cap: number): boolean {
  return width > cap || height > cap;
}

/** Dimensions of level `scale` — the server's iterated `ceil` equals `ceil(dim / scale)`. */
export function levelDims(width: number, height: number, scale: number): [number, number] {
  return [Math.ceil(width / scale), Math.ceil(height / scale)];
}

/** Overview level: the smallest power of 2 that makes the image fit within
 *  `min(OVERVIEW_MAX, cap)` — the cap matters: under the debug override (256 px), an
 *  overview aimed at 4096 would itself be too large for a texture. */
export function overviewScale(width: number, height: number, cap = OVERVIEW_MAX): number {
  const target = Math.min(OVERVIEW_MAX, cap);
  let scale = 1;
  while (
    scale < MAX_SERVER_SCALE &&
    (Math.ceil(width / scale) > target || Math.ceil(height / scale) > target)
  ) {
    scale *= 2;
  }
  return scale;
}

/**
 * Level to display for a given zoom: at 1:1 zoom and beyond, full resolution;
 * when zoomed out, the level whose texels approach the screen pixel (2^floor(log2(1/zoom))).
 * Clamped to the overview level — nothing coarser exists.
 */
export function scaleForZoom(zoom: number, maxScale: number): number {
  if (!(zoom > 0)) return maxScale;
  let scale = 1;
  while (scale * 2 <= 1 / zoom && scale * 2 <= maxScale) scale *= 2;
  return scale;
}

export interface Tile {
  tx: number;
  ty: number;
  /** Rectangle of the tile in LEVEL coordinates — the `?rect=` of the fetch. */
  rect: readonly [number, number, number, number];
  /** Area covered in IMAGE coordinates — the quad that gets drawn. */
  quad: readonly [number, number, number, number];
}

export interface CameraView {
  center: readonly [number, number];
  zoom: number;
  /** Viewport size in device-independent pixels (Camera.vw/vh). */
  vw: number;
  vh: number;
}

/** Tiles of level `scale` covering the visible image region (clamped to the image).
 *  `tileSize` deviates from TILE_SIZE only under the debug override (cap < 2048). */
export function visibleTiles(
  cam: CameraView,
  width: number,
  height: number,
  scale: number,
  tileSize = TILE_SIZE,
): Tile[] {
  const [levelW, levelH] = levelDims(width, height, scale);
  // visible region in image coordinates, then level
  const halfW = cam.vw / 2 / cam.zoom;
  const halfH = cam.vh / 2 / cam.zoom;
  const x0 = Math.max(0, Math.floor((cam.center[0] - halfW) / scale));
  const y0 = Math.max(0, Math.floor((cam.center[1] - halfH) / scale));
  const x1 = Math.min(levelW, Math.ceil((cam.center[0] + halfW) / scale));
  const y1 = Math.min(levelH, Math.ceil((cam.center[1] + halfH) / scale));
  if (x1 <= x0 || y1 <= y0) return [];

  const tiles: Tile[] = [];
  for (let ty = Math.floor(y0 / tileSize); ty * tileSize < y1; ty++) {
    for (let tx = Math.floor(x0 / tileSize); tx * tileSize < x1; tx++) {
      const rx = tx * tileSize;
      const ry = ty * tileSize;
      const rw = Math.min(tileSize, levelW - rx);
      const rh = Math.min(tileSize, levelH - ry);
      tiles.push({
        tx,
        ty,
        rect: [rx, ry, rw, rh],
        quad: [
          rx * scale,
          ry * scale,
          Math.min(rw * scale, width - rx * scale),
          Math.min(rh * scale, height - ry * scale),
        ],
      });
    }
  }
  return tiles;
}

/** Texture cache keys — the existing `view:generation` prefix makes invalidation
 *  by generation free: stale tiles die by LRU and unpinning. */
export function tileKey(
  viewId: string,
  gen: number,
  scale: number,
  tx: number,
  ty: number,
): string {
  return `${viewId}:${gen}:s${scale}:${tx},${ty}`;
}

export function overviewKey(viewId: string, gen: number, scale: number): string {
  return `${viewId}:${gen}:s${scale}:ov`;
}

/**
 * Sub-window of a mask UV transform: the drawn quad covers only the fraction
 * (fx, fy, fw, fh) of the area `uv` used to cover. Composes with the existing preview case
 * (`maskUvTransform`) — a tile of a preview of a giant window reads the right piece.
 */
export function subUv(
  uv: readonly [number, number, number, number],
  fx: number,
  fy: number,
  fw: number,
  fh: number,
): [number, number, number, number] {
  return [uv[0] + fx * uv[2], uv[1] + fy * uv[3], fw * uv[2], fh * uv[3]];
}
