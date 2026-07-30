// Renderer of one panel — the display state of a viewport, on the shared GL context.
//
// Since the "single context" refactor (see sharedGL.ts), this class owns neither
// context nor textures: it holds the state SPECIFIC to a panel — camera, STF, channel, mask,
// curtain, cache keys — and its visible canvas, now a **2D** canvas. `render()` draws
// into the hidden GL canvas then blits to the 2D canvas, within the same synchronous call: without
// `preserveDrawingBuffer`, the GL buffer is only readable up to compositing, and encapsulating
// the sequence here guarantees that no caller can slip an `await` between the two.
//
// # What the 2D canvas changes for the user
//
// It keeps its last blit. When the texture of a hidden panel has been evicted from the global
// cache (budget in bytes, see textureCache.ts), `render()` refrains from blitting the backdrop:
// the old image — a correct one — stays displayed while the panel re-fetches. No black,
// no flicker, whatever the number of open windows.
//
// # Pinning
//
// A **visible** panel pins what it shows (current texture, curtain, mask): those
// entries cannot be evicted. A hidden panel (clientWidth = 0) unpins itself — thirty
// pinned 61 Mpx images would be 11 GB of VRAM — and its textures become plain
// LRU entries again, almost always still there on reactivation.

import { Camera } from './camera';
import {
  hasAlphaChannels,
  isMonoChannels,
  MASK_MODE_CODE,
  TRANSPARENCY_CODE,
} from './shaders';
import { blitSourceRect, sharedGL, type Capabilities, type QuadPass } from './sharedGL';
import { subUv } from './tiles';
import type { TextureEntry } from './textureCache';
import type { StfChannel } from '../api/types';

export type { Capabilities } from './sharedGL';

export interface ImageInfo {
  width: number;
  height: number;
  channels: number;
}

/**
 * Tiled image (beyond `MAX_TEXTURE_SIZE`): an always-resident overview drawn
 * first, tiles of the current level on top. Mutually exclusive with `currentKey` — a panel
 * shows either a texture or a mosaic. The curtain is not rendered in mosaic mode
 * (an accepted limitation).
 */
export interface Mosaic {
  /** Dimensions of the full-resolution image — the camera reasons within them. */
  width: number;
  height: number;
  overviewKey: string;
  /** Tiles to draw: cache key + area covered in image coordinates. */
  tiles: ReadonlyArray<{ key: string; quad: readonly [number, number, number, number] }>;
}

const IDENTITY_STF: StfChannel = { shadows: 0, midtones: 0.5, highlights: 1 };

export class ViewportRenderer {
  readonly camera = new Camera(1, 1);

  stfEnabled = true;
  stfChannels: readonly StfChannel[] = [IDENTITY_STF];
  channel = 'rgb';
  /** Rendering of the alpha < 1 areas, set from `ViewportState.transparency_mode`. */
  transparency: number = TRANSPARENCY_CODE.brush;

  /**
   * Mask compositing, set by the caller from the snapshot.
   *
   * `mode` is 0 when there is no mask or when it is hidden — that is also the default, so
   * a consumer of the renderer that knows nothing about masks (the real-time preview) suffers
   * nothing from it. `uv` unfolds the window's mask onto the displayed texture, which may be
   * only a preview: without it, the whole mask would be squeezed onto the preview's rectangle.
   */
  mask: {
    mode: number;
    inverted: boolean;
    color: readonly [number, number, number];
    uv: readonly [number, number, number, number];
  } = { mode: MASK_MODE_CODE.off, inverted: false, color: [1, 0, 0], uv: [0, 0, 1, 1] };

  private readonly ctx: CanvasRenderingContext2D;
  private currentKey: string | null = null;
  private mosaicState: Mosaic | null = null;
  private maskKey: string | null = null;
  private curtainState: { key: string; split: number } | null = null;
  private visible = true;

  /**
   * @param ownerId pinning identity in the global cache — `win.id` for a viewport,
   *                `rtp:<owner>` for a preview. Two panels never share an
   *                ownerId; they may however pin the same keys (the viewport
   *                and the preview of one and the same view show the same texture).
   */
  constructor(
    readonly canvas: HTMLCanvasElement,
    private readonly ownerId: string,
  ) {
    // Create the singleton right away: if WebGL2 is missing, the error must surface here — at
    // the panel's mount, where it was raised before the refactor — not at the first render.
    sharedGL();
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) throw new Error("canvas 2D indisponible — le viewport ne peut pas s'afficher.");
    this.ctx = ctx;
  }

  get caps(): Capabilities {
    return sharedGL().caps;
  }

  get hasImage(): boolean {
    return this.currentKey !== null || this.mosaicState !== null;
  }

  get mosaic(): Mosaic | null {
    return this.mosaicState;
  }

  /**
   * Switches the panel into mosaic mode (or out of it with `null`). Replaces the current
   * texture: the two modes are mutually exclusive. Called on every update of the set of
   * visible tiles — that is cheap, drawing only reads the cache.
   */
  setMosaic(mosaic: Mosaic | null): void {
    this.mosaicState = mosaic;
    if (mosaic) {
      this.currentKey = null;
      this.camera.setImageSize(mosaic.width, mosaic.height);
    }
    this.repin();
  }

  /**
   * Before/after comparison within the same viewport: to the right of `split` (0..1), the
   * texture `key` is drawn instead of the current one. A second draw call under a scissor rather
   * than a shader with two samplers — the GPU already has both textures.
   */
  get curtain(): { key: string; split: number } | null {
    return this.curtainState;
  }

  set curtain(value: { key: string; split: number } | null) {
    this.curtainState = value;
    this.repin();
  }

  /**
   * True if this key is already in GPU memory — hence displayable without any transfer.
   *
   * This is what the caller asks before starting a `fetch`: on an A/B toggle, the
   * answer is yes one time out of two. With the global cache, it is also yes when it is
   * ANOTHER panel that paid for the upload — the RTP preview curtains over the viewport's texture.
   */
  hasCached(key: string): boolean {
    return sharedGL().cache.has(key);
  }

  /** Displays a texture already in cache. Returns `false` if it is not (or no longer) there. */
  select(key: string): boolean {
    const entry = sharedGL().cache.get(key); // get() touches the LRU
    if (!entry) return false;
    this.adopt(key, entry);
    return true;
  }

  private adopt(key: string, entry: TextureEntry): void {
    this.currentKey = key;
    this.mosaicState = null; // the two modes are mutually exclusive
    this.camera.setImageSize(entry.quad[0], entry.quad[1]);
    this.repin();
  }

  /**
   * Stores a mosaic tile (or the overview) in the global cache, without adopting it as the
   * current texture — it is `setMosaic` that decides what gets drawn.
   */
  uploadTile(buffer: ArrayBuffer, info: ImageInfo, key: string): void {
    const texture = this.tryCreate(buffer, info, 'linear');
    if (!texture) return; // context lost: glEpoch will wake the effect, which will re-fetch
    sharedGL().cache.put(key, {
      texture,
      quad: [info.width, info.height],
      mono: isMonoChannels(info.channels),
      hasAlpha: hasAlphaChannels(info.channels),
      bytes: info.width * info.height * info.channels * 2,
    });
    this.repin();
  }

  /**
   * Sends the float16 pixels to the GPU and keeps the texture under `key` in the global cache.
   *
   * @param buffer raw contiguous data (H, W, C), as served by /api/pixels
   * @param key    stable identity of the pixels — `view:generation`, like the server cache
   * @param quad   area covered in image coordinates, when it differs from the texture
   *               (a decimated preview covers the original it stands for)
   */
  uploadImage(buffer: ArrayBuffer, info: ImageInfo, key: string, quad?: [number, number]): void {
    const shared = sharedGL();
    const texture = this.tryCreate(buffer, info, 'linear');
    if (!texture) return; // context lost: glEpoch will wake the effect, which will re-fetch
    const entry: TextureEntry = {
      texture,
      quad: quad ?? [info.width, info.height],
      mono: isMonoChannels(info.channels),
      hasAlpha: hasAlphaChannels(info.channels),
      bytes: info.width * info.height * info.channels * 2,
    };
    shared.cache.put(key, entry);
    this.adopt(key, entry);
  }

  /**
   * Creates the texture, or returns `null` if the context is lost — including when the loss
   * happens DURING the call (the fetch left before, came back after: `texImage2D` then fails
   * with 0x9242). This is not an error to log, it is a replayed event:
   * restoration bumps `glEpoch`, the loading effect wakes up, and since the cache does not have
   * the key, it re-fetches.
   */
  private tryCreate(
    buffer: ArrayBuffer,
    info: ImageInfo,
    filter: 'linear' | 'nearest',
  ): WebGLTexture | null {
    const shared = sharedGL();
    if (shared.isLost()) return null;
    try {
      return shared.createTexture(buffer, info.width, info.height, info.channels, filter);
    } catch (error) {
      if (shared.isLost()) return null;
      throw error;
    }
  }

  /** True if the mask of this key (`mask:window:generation`) is already in GPU memory. */
  hasMask(key: string): boolean {
    return this.maskKey === key && sharedGL().cache.has(key);
  }

  /**
   * Uploads the mask as a texture. Touches neither the camera nor the quad.
   *
   * NEAREST, and not LINEAR: a mask is a per-pixel weight. Interpolating would make the
   * `replace` mode lie, where the value read on screen must be the one the process will apply.
   * Idempotent on the key: the panel may call on every snapshot without re-uploading.
   */
  uploadMask(buffer: ArrayBuffer, info: ImageInfo, key: string): void {
    if (this.hasMask(key)) return;
    const shared = sharedGL();
    const texture = this.tryCreate(buffer, info, 'nearest');
    if (!texture) return;
    shared.cache.put(key, {
      texture,
      quad: [info.width, info.height],
      mono: isMonoChannels(info.channels),
      hasAlpha: hasAlphaChannels(info.channels),
      bytes: info.width * info.height * info.channels * 2,
    });
    this.maskKey = key;
    this.repin();
  }

  /** Forgets the mask — called when the window no longer has one. Eviction will clean up. */
  clearMask(): void {
    this.maskKey = null;
    this.mask = { ...this.mask, mode: MASK_MODE_CODE.off };
    this.repin();
  }

  /** Aligns the canvas size with its CSS size and the HiDPI ratio. True if that changed. */
  syncSize(): boolean {
    const dpr = window.devicePixelRatio || 1;
    const cssWidth = this.canvas.clientWidth;
    const cssHeight = this.canvas.clientHeight;
    const width = Math.max(1, Math.round(cssWidth * dpr));
    const height = Math.max(1, Math.round(cssHeight * dpr));
    // Reassign only if the size changed: reassigning width/height CLEARS the canvas, and
    // it is its content that covers the re-fetches (see header). Idiom from ui/canvas.ts.
    const changed = this.canvas.width !== width || this.canvas.height !== height;
    if (changed) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
    // The camera reasons in device-independent pixels, as ViewportState.update_geometry does
    this.camera.updateGeometry(cssWidth, cssHeight, dpr);
    return changed;
  }

  render(): void {
    const shared = sharedGL();
    if (shared.isLost()) return; // restoration will re-trigger through glEpoch

    // Hidden panel (inactive dockview tab: detached element, clientWidth = 0): nothing to
    // paint, and above all UNPIN — that is what bounds the VRAM whatever the
    // number of open tabs. The ResizeObserver will bring a render back on reactivation.
    if (this.canvas.clientWidth === 0 || this.canvas.clientHeight === 0) {
      if (this.visible) {
        this.visible = false;
        shared.cache.unpin(this.ownerId);
      }
      return;
    }
    if (!this.visible) {
      this.visible = true;
      this.repin();
    }

    this.syncSize();
    const w = this.canvas.width;
    const h = this.canvas.height;

    const entry = this.currentKey ? shared.cache.get(this.currentKey) : null;
    if (this.currentKey && !entry) {
      // The texture was evicted while the panel was hidden. Do NOT paint the backdrop:
      // the 2D canvas keeps its last image — a correct one — while the panel's loading
      // effect re-fetches (it re-checks hasCached on every wake-up). This is the
      // architecture's structural anti-flicker.
      return;
    }
    if (this.mosaicState && !shared.cache.get(this.mosaicState.overviewKey)) {
      // Same logic for a mosaic: without the overview (evicted, or a new generation not
      // fetched yet), painting would show holes — the last blit stays displayed.
      return;
    }

    shared.ensureSize(w, h);
    shared.beginRegion(w, h);
    this.drawScene(entry, w, h);
    shared.endRegion();
    this.blit(w, h);
  }

  /**
   * Draws the panel's scene into the current GL region — single texture (the historical
   * path, curtain included) or mosaic (overview under the tiles of the current level).
   * Shared between `render()` and the magnifier: the magnifier of a tiled image magnifies the
   * resident texels, with sharpness bounded by the loaded level (an accepted limitation).
   */
  private drawScene(entry: TextureEntry | null | undefined, w: number, h: number): void {
    const shared = sharedGL();
    if (this.mosaicState) {
      const mosaic = this.mosaicState;
      const overview = shared.cache.get(mosaic.overviewKey);
      if (!overview) return;
      shared.drawQuad(this.pass(overview, [0, 0, mosaic.width, mosaic.height]));
      for (const tile of mosaic.tiles) {
        const cached = shared.cache.get(tile.key);
        if (cached) shared.drawQuad(this.pass(cached, tile.quad));
      }
      return;
    }
    if (entry) {
      shared.drawQuad(this.pass(entry));
      this.drawCurtain(entry, w, h);
    }
  }

  /**
   * Magnifier: a second render of the same texture, in a corner, centered on the cursor.
   *
   * Two draw calls rather than a pixel copy: the GPU already has the texture, so it may as well
   * redraw it. Called AFTER `render()` within the same rAF callback: the GL region still carries
   * the panel's image, the magnifier is added to it and the whole thing is blitted again.
   *
   * @param cursor image point under the cursor
   * @param rect   area of the magnifier, in CSS pixels (origin at the canvas's top left)
   * @param factor magnification
   */
  renderLoupe(
    cursor: readonly [number, number],
    rect: { x: number; y: number; size: number },
    factor: number,
  ): void {
    const shared = sharedGL();
    if (shared.isLost() || !this.visible) return;
    const entry = this.currentKey ? shared.cache.get(this.currentKey) : null;
    if (!entry && !this.mosaicState) return;

    const dpr = this.camera.dpr;
    const w = this.canvas.width;
    const h = this.canvas.height;
    const px = Math.round(rect.x * dpr);
    const size = Math.round(rect.size * dpr);
    // WebGL counts its viewports from the BOTTOM of the region; the DOM from the top of the canvas.
    const py = Math.round(h - (rect.y + rect.size) * dpr);

    const saved = { zoom: this.camera.zoom, center: this.camera.center, vw: this.camera.vw, vh: this.camera.vh };
    this.camera.updateGeometry(rect.size, rect.size, dpr);
    this.camera.setZoom(saved.zoom * factor);
    this.camera.setCenter(cursor);

    shared.withViewport({ x: px, y: py, w: size, h: size }, () => {
      this.drawScene(entry, size, size);
    });
    shared.endRegion();

    this.camera.updateGeometry(saved.vw, saved.vh, dpr);
    this.camera.setZoom(saved.zoom);
    this.camera.setCenter(saved.center);
    this.blit(w, h);
  }

  dispose(): void {
    // Nothing GL to release: the textures belong to the global cache, which decides. We only
    // give back our pins — that is what makes them evictable.
    sharedGL().cache.unpin(this.ownerId);
  }

  // --- private ---------------------------------------------------------------

  /**
   * @param rect area covered `[x, y, w, h]` in image coordinates, for a quad that does not
   *             start at the origin (tile, overview of a mosaic). The mask follows: its
   *             UV window narrows to the same fraction of the image (`subUv`), which
   *             composes with the existing preview case.
   */
  private pass(entry: TextureEntry, rect?: readonly [number, number, number, number]): QuadPass {
    const maskEntry = this.maskKey ? sharedGL().cache.get(this.maskKey) : null;
    const total = this.mosaicState;
    let maskUv = this.mask.uv;
    if (rect && total && total.width > 0 && total.height > 0) {
      maskUv = subUv(
        this.mask.uv,
        rect[0] / total.width,
        rect[1] / total.height,
        rect[2] / total.width,
        rect[3] / total.height,
      );
    }
    return {
      texture: entry.texture,
      quad: rect ? [rect[2], rect[3]] : entry.quad,
      ...(rect ? { origin: [rect[0], rect[1]] as const } : {}),
      clip: this.camera.clipMatrix(),
      mono: entry.mono,
      hasAlpha: entry.hasAlpha,
      transparency: this.transparency,
      stfEnabled: this.stfEnabled,
      stfChannels: this.stfChannels,
      channel: this.channel,
      mask: {
        texture: maskEntry?.texture ?? null,
        mono: maskEntry?.mono ?? false,
        mode: this.mask.mode,
        inverted: this.mask.inverted,
        color: this.mask.color,
        uv: maskUv,
      },
    };
  }

  /**
   * Redraws the right half with the other texture — the "before/after" under a handle.
   *
   * A scissor rather than a shader with two samplers: two draw calls on
   * already-resident textures, and the STF shader stays strictly identical between the two
   * halves — the condition for the comparison to mean anything.
   */
  private drawCurtain(current: TextureEntry, w: number, h: number): void {
    if (!this.curtainState) return;
    const other = sharedGL().cache.get(this.curtainState.key);
    if (!other) return;
    const split = Math.min(Math.max(this.curtainState.split, 0), 1);
    const x = Math.round(w * split);
    if (w - x <= 0) return;
    sharedGL().drawQuad(
      { ...this.pass(current), texture: other.texture, mono: other.mono, hasAlpha: other.hasAlpha },
      { x, y: 0, w: w - x, h },
    );
  }

  /** Copies the GL region to the 2D canvas — same task as the drawing, never an await before. */
  private blit(w: number, h: number): void {
    const shared = sharedGL();
    const { sx, sy, sw, sh } = blitSourceRect(shared.canvas.height, w, h);
    // Reassigning width/height (syncSize) resets the 2D context's state: setting the
    // smoothing again on every blit costs next to nothing and is always right.
    this.ctx.imageSmoothingEnabled = false;
    this.ctx.drawImage(shared.canvas, sx, sy, sw, sh, 0, 0, sw, sh);
  }

  private repin(): void {
    if (!this.visible) return;
    const keys: string[] = [];
    if (this.currentKey) keys.push(this.currentKey);
    if (this.mosaicState) {
      // the overview and the VISIBLE tiles only: tiles that have left the view
      // become plain LRU entries again — that is what bounds the VRAM of a gigapixel
      keys.push(this.mosaicState.overviewKey);
      for (const tile of this.mosaicState.tiles) keys.push(tile.key);
    }
    if (this.curtainState) keys.push(this.curtainState.key);
    if (this.maskKey) keys.push(this.maskKey);
    sharedGL().cache.pin(this.ownerId, keys);
  }
}
