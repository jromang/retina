// Loading the tiles of a tiled image — all the asynchrony of tiling lives here.
//
// The "blit pact" (renderer.ts) forbids any await between drawing and blitting: this module
// is therefore entirely OUTSIDE `render()`. Rendering only reads the texture cache;
// the fetches leave in their own tasks, upload on arrival, then request a new
// frame — exactly the protocol of the existing loading effect.
//
// Desired set ↔ in flight: on every camera gesture, `update()` recomputes the visible
// tiles, aborts the fetches that have become useless (fast pan: nobody is interested in the
// tile we have left) and starts the missing ones, debounced so as not to machine-gun the server
// during a continuous zoom. The always-resident overview covers the wait.

import { client } from '../api/client';
import {
  overviewScale,
  scaleForZoom,
  TILE_SIZE,
  tileKey,
  visibleTiles,
  type CameraView,
  type Tile,
} from './tiles';

/** Simultaneous fetches — beyond that, the server serializes on its executor anyway. */
const MAX_CONCURRENT = 4;
/** Debounce of the launches during a gesture (continuous pan/zoom). */
const DEBOUNCE_MS = 120;

export interface MosaicTileRef {
  key: string;
  quad: readonly [number, number, number, number];
}

export class TileLoader {
  /** Overview level — beyond it, there is nothing to tile. */
  readonly maxScale: number;
  /** Effective tile side — TILE_SIZE, except under the debug override (smaller cap). */
  readonly tileSize: number;

  private desired = new Map<string, { tile: Tile; scale: number }>();
  private readonly inflight = new Map<string, AbortController>();
  private debounceTimer: ReturnType<typeof setTimeout> | undefined;
  private disposed = false;

  constructor(
    private readonly viewId: string,
    private readonly gen: number,
    private readonly width: number,
    private readonly height: number,
    cap: number,
    private readonly hasCached: (key: string) => boolean,
    private readonly onTile: (key: string, buffer: ArrayBuffer, w: number, h: number) => void,
  ) {
    this.maxScale = overviewScale(width, height, cap);
    this.tileSize = Math.min(TILE_SIZE, cap);
  }

  /**
   * Tiles of the current level for this camera — the list that `setMosaic` will display.
   * Triggers (debounced) the fetches of the tiles missing from the cache.
   */
  update(cam: CameraView): MosaicTileRef[] {
    const scale = scaleForZoom(cam.zoom, this.maxScale);
    if (scale >= this.maxScale) {
      // the overview is enough at this zoom: nothing to tile, and nothing left to fetch
      this.setDesired(new Map());
      return [];
    }
    const tiles = visibleTiles(cam, this.width, this.height, scale, this.tileSize);
    const desired = new Map(
      tiles.map((tile) => [
        tileKey(this.viewId, this.gen, scale, tile.tx, tile.ty),
        { tile, scale },
      ]),
    );
    this.setDesired(desired);
    return [...desired.entries()].map(([key, { tile }]) => ({ key, quad: tile.quad }));
  }

  dispose(): void {
    this.disposed = true;
    clearTimeout(this.debounceTimer);
    for (const controller of this.inflight.values()) controller.abort();
    this.inflight.clear();
    this.desired.clear();
  }

  private setDesired(desired: Map<string, { tile: Tile; scale: number }>): void {
    this.desired = desired;
    for (const [key, controller] of this.inflight) {
      if (!desired.has(key)) {
        controller.abort();
        this.inflight.delete(key);
      }
    }
    clearTimeout(this.debounceTimer);
    this.debounceTimer = setTimeout(() => this.pump(), DEBOUNCE_MS);
  }

  private pump(): void {
    if (this.disposed) return;
    for (const [key, { tile, scale }] of this.desired) {
      if (this.inflight.size >= MAX_CONCURRENT) return;
      if (this.inflight.has(key) || this.hasCached(key)) continue;
      const controller = new AbortController();
      this.inflight.set(key, controller);
      void this.fetchTile(key, tile, scale, controller).finally(() => {
        this.inflight.delete(key);
        this.pump(); // a slot has freed up: the next tile leaves right away
      });
    }
  }

  private async fetchTile(
    key: string,
    tile: Tile,
    scale: number,
    controller: AbortController,
  ): Promise<void> {
    try {
      const [x, y, w, h] = tile.rect;
      const response = await client.fetch(
        `/api/pixels/${encodeURIComponent(this.viewId)}.f16` +
          `?gen=${this.gen}&scale=${scale}&rect=${x},${y},${w},${h}`,
        { signal: controller.signal },
      );
      // 409 = stale generation (a snapshot will follow, the effect will rebuild the loader),
      // 404 = view closed in the meantime: the same benign races as the loading effect.
      if (response.status === 409 || response.status === 404) return;
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const buffer = await response.arrayBuffer();
      if (controller.signal.aborted || this.disposed) return;
      this.onTile(key, buffer, w, h);
    } catch (error) {
      if (!controller.signal.aborted) console.error('chargement de tuile', error);
    }
  }
}
