// The viewport: toolbar, breadcrumb, WebGL2 canvas and interaction layer.
//
// # Optimistic rendering
//
// Pan and zoom move the camera **locally** and redraw immediately: at 60 FPS, a
// server round trip per frame would be perceptible, and above all would produce an unreadable
// avalanche of Python echoes. Only at the end of the gesture does the client push its state
// through `app.set_viewport` — a single echo, clean and replayable, as if the user had typed the
// command. That is the behavior of the former Qt shell, transposed.
//
// # Interaction modes
//
// What a click does depends on the mode, which lives in the domain (`ViewportState`) and not
// here: `app.set_interaction_mode('pan')` typed in the console changes the mouse's behavior. The
// destructive gestures — creating or moving a preview — go through `app.*` and leave their echo.

import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import type { ViewState, WindowState } from '../api/types';
import {
  carriesAnything,
  carriesApplicable,
  carriesFile,
  readDragPayload,
  readFilePath,
} from '../dnd/dnd';
import { runContainer, runProcess } from '../processes/jobs';
import { openProject } from '../project/project';
import { windows } from '../state/store';
import { rememberView } from './ab';
import { dynamicTool, type DynamicToolEvent } from './dynamicTool';
import { drawOverlay, viewAt, type DropTarget, type Rect } from './overlay';
import { ViewportRenderer } from './renderer';
import { glEpoch } from './sharedGL';
import {
  MASK_MODE_CODE,
  maskCompositing,
  maskUvTransform,
  transparencyCode,
} from './shaders';
import { TileLoader } from './tileLoader';
import { levelDims, needsTiling, overviewKey, overviewScale, tileCap } from './tiles';
import { Breadcrumb, ViewportToolbar } from './ViewportToolbar';

const WHEEL_SETTLE_MS = 220;
const GEOMETRY_SETTLE_MS = 150;
const READOUT_INTERVAL_MS = 33; // ~30 Hz: beyond that, we saturate the link for nothing
/** A drag of less than 2 px is a click, not a preview. */
const MIN_PREVIEW_PX = 2;
const LOUPE_SIZE = 132;
const LOUPE_FACTOR = 8;

interface Props {
  window: WindowState;
  view: ViewState;
  onStatus?: (status: ViewportStatus) => void;
}

export interface ViewportStatus {
  zoom: number;
  cursor: { x: number; y: number } | null;
  /** Per-channel means under the cursor, read from the server's float32. */
  values: number[] | null;
  /** RA/Dec in degrees of the probed pixel, if the window carries an astrometric solution. */
  celestial: { ra: number; dec: number } | null;
  /** Decimals to display (`ReadoutOptions.precision`, settable from the console). */
  precision: number;
  gpu: string;
}

/** Response of `app.readout` (mirror of `ImageWindow.readout`). */
interface Readout {
  x: number;
  y: number;
  celestial: { ra: number; dec: number } | null;
  channels: Array<{ mean: number; median: number; min: number; max: number }>;
}

type Gesture =
  | { kind: 'pan' }
  | { kind: 'rubber'; origin: readonly [number, number] }
  | { kind: 'move-preview'; id: string; start: Rect; grab: readonly [number, number] }
  | null;

export function ViewportPanel({ window: win, view, onStatus }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<ViewportRenderer | null>(null);
  const frameRef = useRef(0);
  const gestureRef = useRef<Gesture>(null);
  const wheelRef = useRef<number | null>(null);
  const loadedRef = useRef<string>('');
  // Tiling (image beyond the texture cap): the loader fetches the visible tiles,
  // the meta lets the rAF rebuild the mosaic on every camera gesture.
  const tileLoaderRef = useRef<TileLoader | null>(null);
  const mosaicMetaRef = useRef<{ overviewKey: string; width: number; height: number } | null>(
    null,
  );
  const readoutRef = useRef(0);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);
  // Incremented when the panel must re-check its textures: tab reactivation
  // (they may have been evicted) or GL context restoration (they are all dead).
  const [wakeTick, setWakeTick] = useState(0);
  const [rubber, setRubber] = useState<Rect | null>(null);
  const [loupe, setLoupe] = useState<readonly [number, number] | null>(null);

  // Read by handlers that do not re-subscribe to the signals: a ref avoids recreating
  // the callbacks on every snapshot.
  const stateRef = useRef({ win, view, dropTarget, rubber, loupe });
  stateRef.current = { win, view, dropTarget, rubber, loupe };

  const mode = win.viewport.interaction_mode;
  // Read in the component's body: this is what subscribes the panel to the signal, hence what
  // makes the cursor and the chrome follow when a panel arms or disarms its tool.
  const tool = dynamicTool.value;

  const paintOverlay = () => {
    const renderer = rendererRef.current;
    const overlay = overlayRef.current;
    if (!renderer || !overlay) return;
    const current = stateRef.current;
    drawOverlay(overlay, renderer.camera, {
      views: current.win.views,
      activeViewId: current.view.id,
      drop: current.dropTarget,
      rubber: current.rubber,
      loupe: current.loupe && current.win.viewport.readout.show_loupe ? { size: LOUPE_SIZE } : null,
      overlays: current.win.viewport.overlays,
      chrome: tool?.chrome ? (ctx, camera) => tool.chrome!(ctx, camera, current.win.id) : null,
    });
  };

  /** Recomputes the visible tiles for the current camera and lays them on the renderer.
   *  All the asynchrony (fetching the missing ones) is in the loader — rendering only
   *  reads the cache, the blit pact is respected by construction. */
  const refreshMosaic = () => {
    const renderer = rendererRef.current;
    const loader = tileLoaderRef.current;
    const meta = mosaicMetaRef.current;
    if (!renderer || !loader || !meta) return;
    const cam = renderer.camera;
    const tiles = loader.update({ center: cam.center, zoom: cam.zoom, vw: cam.vw, vh: cam.vh });
    renderer.setMosaic({
      width: meta.width,
      height: meta.height,
      overviewKey: meta.overviewKey,
      tiles,
    });
  };

  const scheduleRender = () => {
    if (frameRef.current) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = 0;
      const renderer = rendererRef.current;
      if (!renderer) return;
      refreshMosaic(); // before rendering: the mosaic follows the camera
      renderer.render();
      // `show_loupe` was serialized in the snapshot without anything reading it: the magnifier
      // always showed, and the option existed for the console only.
      const cursor = stateRef.current.win.viewport.readout.show_loupe
        ? stateRef.current.loupe
        : null;
      if (cursor) {
        renderer.renderLoupe(cursor, { x: renderer.camera.vw - LOUPE_SIZE - 8, y: 8, size: LOUPE_SIZE }, LOUPE_FACTOR);
      }
      paintOverlay();
    });
  };

  const commitViewport = () => {
    const camera = rendererRef.current?.camera;
    if (!camera) return;
    // The window may have been closed between the gesture and its send (the panel unmounts
    // asynchronously): the domain would answer "unknown window", which is not a fault but
    // a race. Same reasoning as the 409 of the pixel loading.
    if (!windows.value.some((w) => w.id === win.id)) return;
    void client
      .call('app.set_viewport', {
        center: [camera.center[0], camera.center[1]],
        zoom: camera.zoom,
        window: win.id,
      })
      // Silent, and deliberately so: this call is the **late echo** of a camera gesture
      // (see "optimistic rendering" at the top of the file). If the window has disappeared in the
      // meantime, there is nothing left to commit — the server is right to refuse, and the client
      // has no reason to shout. The guard above catches the common case; what remains is the pure
      // race, which no client-side check can win.
      .catch(() => undefined);
  };

  // --- life cycle of the GL context ----------------------------------------
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let renderer: ViewportRenderer;
    try {
      renderer = new ViewportRenderer(canvas, win.id);
    } catch (error) {
      console.error(error);
      return;
    }
    rendererRef.current = renderer;
    scheduleRender();

    let geometryTimer: number | undefined;
    const observer = new ResizeObserver(() => {
      renderer.syncSize();
      scheduleRender();
      // Tab reactivation: dockview detaches hidden panels (zero size), and
      // reattaching re-triggers the observation. The panel's textures may have been
      // evicted during the absence — wake the loading effects, which re-check the
      // cache and only re-fetch if necessary.
      if (canvas.clientWidth > 0) setWakeTick((t) => t + 1);
      globalThis.clearTimeout(geometryTimer);
      geometryTimer = globalThis.setTimeout(() => {
        void client
          .call('viewport.report_geometry', {
            window: win.id,
            vw: renderer.camera.vw,
            vh: renderer.camera.vh,
            dpr: renderer.camera.dpr,
          })
          .catch(() => undefined);
      }, GEOMETRY_SETTLE_MS);
    });
    observer.observe(canvas);

    return () => {
      observer.disconnect();
      globalThis.clearTimeout(geometryTimer);
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
      frameRef.current = 0;
      tileLoaderRef.current?.dispose();
      tileLoaderRef.current = null;
      mosaicMetaRef.current = null;
      renderer.dispose();
      rendererRef.current = null;
    };
  }, [win.id]);

  // GL context restoration: everything that lived in VRAM is dead. Forget what we
  // believed was loaded and wake the effects — declared before them, since the effects of one
  // render run in declaration order.
  useEffect(() => {
    if (glEpoch.value === 0) return;
    loadedRef.current = '';
    setWakeTick((t) => t + 1);
  }, [glEpoch.value]);

  // --- loading of the pixels ------------------------------------------------
  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    const key = `${view.id}:${view.pixel_gen}`;

    // --- tiled path: the image cannot become ONE texture ----------------------
    const cap = tileCap(renderer.caps.maxTextureSize);
    if (needsTiling(view.width, view.height, cap)) {
      const scale = overviewScale(view.width, view.height, cap);
      const ovKey = overviewKey(view.id, view.pixel_gen, scale);
      if (loadedRef.current === key && renderer.hasCached(ovKey)) {
        refreshMosaic();
        scheduleRender();
        return;
      }
      tileLoaderRef.current?.dispose();
      tileLoaderRef.current = new TileLoader(
        view.id,
        view.pixel_gen,
        view.width,
        view.height,
        cap,
        (k) => renderer.hasCached(k),
        (k, buffer, w, h) => {
          if (rendererRef.current !== renderer) return;
          renderer.uploadTile(buffer, { width: w, height: h, channels: view.channels }, k);
          refreshMosaic();
          scheduleRender();
        },
      );
      mosaicMetaRef.current = { overviewKey: ovKey, width: view.width, height: view.height };

      let cancelled = false;
      void (async () => {
        try {
          const response = await client.fetch(
            `/api/pixels/${encodeURIComponent(view.id)}.f16?gen=${view.pixel_gen}&scale=${scale}`,
          );
          if (response.status === 409 || response.status === 404) return; // a snapshot will follow
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const buffer = await response.arrayBuffer();
          if (cancelled || rendererRef.current !== renderer) return;
          const [levelW, levelH] = levelDims(view.width, view.height, scale);
          const firstLoad = !renderer.hasImage;
          renderer.uploadTile(buffer, { width: levelW, height: levelH, channels: view.channels }, ovKey);
          loadedRef.current = key;
          refreshMosaic(); // lays down the mosaic (and the image size on the camera)
          if (firstLoad) {
            renderer.camera.zoomToFit();
            commitViewport();
            refreshMosaic(); // the zoom has changed level
          }
          scheduleRender();
        } catch (error) {
          console.error('chargement des pixels', error);
        }
      })();
      return () => {
        cancelled = true;
      };
    }
    // --- historical path: one texture, one quad — strictly unchanged ----------
    tileLoaderRef.current?.dispose();
    tileLoaderRef.current = null;
    mosaicMetaRef.current = null;
    // `loadedRef` alone is no longer enough: with the global cache, an "already loaded" texture
    // may have been evicted while the panel was hidden. `hasCached` re-checks; during
    // the possible re-fetch, the 2D canvas keeps its last image — that is the anti-flicker.
    if (loadedRef.current === key && renderer.hasCached(key)) return;

    // Already in GPU memory: this is the case of an A/B toggle, and it must cost nothing. Without
    // this short circuit, coming back to a view one has just left would re-transfer its
    // pixels — 150 MB on a 26 Mpx frame, for an image we already have.
    rememberView(loadedRef.current.split(':')[0] ?? '', view.id);

    if (renderer.select(key)) {
      loadedRef.current = key;
      scheduleRender();
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const response = await client.fetch(
          `/api/pixels/${encodeURIComponent(view.id)}.f16?gen=${view.pixel_gen}`,
        );
        // 409 = stale generation, a snapshot will follow. 404 = the view was closed between
        // the snapshot and the request — the same kind of race, and nothing to report either.
        if (response.status === 409 || response.status === 404) return;
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const buffer = await response.arrayBuffer();
        if (cancelled || rendererRef.current !== renderer) return;

        const firstLoad = !renderer.hasImage;
        renderer.uploadImage(
          buffer,
          { width: view.width, height: view.height, channels: view.channels },
          key,
        );
        loadedRef.current = key;
        if (firstLoad) {
          renderer.camera.zoomToFit();
          commitViewport();
        }
        scheduleRender();
      } catch (error) {
        console.error('chargement des pixels', error);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [view.id, view.pixel_gen, view.width, view.height, view.channels, wakeTick]);

  // --- loading of the mask --------------------------------------------------
  // Separate from the pixel loading: the mask belongs to the window, the pixels to the view.
  // Mixing them would re-upload the mask on every preview change, and would lose it on the
  // first undo.
  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    const mask = win.mask;
    if (!mask) {
      renderer.clearMask();
      scheduleRender();
      return;
    }
    const key = `mask:${win.id}:${mask.gen}`;
    if (renderer.hasMask(key)) return;

    // Mask of a window beyond the texture cap: a single decimated texture
    // (`?scale=`), displayed as is — `u_maskUv` is normalized, nothing else changes.
    // The process itself applies the real mask on the server side: only the DISPLAY is decimated
    // (an accepted limitation). The guard is on the dimensions of the WINDOW: a
    // small preview of a giant window has a giant mask.
    const cap = tileCap(renderer.caps.maxTextureSize);
    const maskScale = needsTiling(mask.width, mask.height, cap)
      ? overviewScale(mask.width, mask.height, cap)
      : 1;
    const scaleQuery = maskScale > 1 ? `&scale=${maskScale}` : '';
    const [maskW, maskH] = levelDims(mask.width, mask.height, maskScale);

    let cancelled = false;
    void (async () => {
      try {
        const response = await client.fetch(
          `/api/mask/${encodeURIComponent(win.id)}.f16?gen=${mask.gen}${scaleQuery}`,
        );
        if (response.status === 409 || response.status === 404) return; // a snapshot will follow
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const buffer = await response.arrayBuffer();
        if (cancelled || rendererRef.current !== renderer) return;
        renderer.uploadMask(buffer, { width: maskW, height: maskH, channels: mask.channels }, key);
        scheduleRender();
      } catch (error) {
        console.error('chargement du masque', error);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [win.id, win.mask?.gen, win.mask?.width, win.mask?.height, win.mask?.channels, wakeTick]);

  // --- synchronization from the domain --------------------------------------
  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    renderer.stfEnabled = view.stf.enabled && win.viewport.stf_enabled;
    renderer.stfChannels = view.stf.channels.length > 0 ? view.stf.channels : renderer.stfChannels;
    renderer.channel = win.viewport.channel;
    renderer.transparency = transparencyCode(win.viewport.transparency_mode);
    // A mask that is present but hidden does not compose; `mask.enabled` (the effect on the
    // processes) does not come in here — one wants to be able to look at a mask one has disabled.
    const compositing = maskCompositing(win.viewport.mask_display_mode);
    renderer.mask = {
      mode: win.mask && win.viewport.mask_visible ? compositing.mode : MASK_MODE_CODE.off,
      inverted: win.mask?.inverted ?? false,
      color: compositing.color,
      uv: maskUvTransform(view.rect, win.width, win.height),
    };
    if (!gestureRef.current) {
      renderer.camera.setZoom(win.viewport.zoom);
      renderer.camera.setCenter(win.viewport.center);
    }
    scheduleRender();
  }, [
    view.stf,
    view.rect,
    win.views,
    win.width,
    win.height,
    win.mask,
    win.viewport.zoom,
    win.viewport.center,
    win.viewport.channel,
    win.viewport.stf_enabled,
    win.viewport.mask_display_mode,
    win.viewport.mask_visible,
    win.viewport.transparency_mode,
  ]);

  // Arming or disarming a tool changes what the layer draws: repaint without waiting for the
  // next mouse move.
  useEffect(() => {
    scheduleRender();
  }, [tool?.id]);

  // --- readout --------------------------------------------------------------
  const probeReadout = (point: readonly [number, number]) => {
    const now = performance.now();
    if (now - readoutRef.current < READOUT_INTERVAL_MS) return;
    readoutRef.current = now;
    // Deliberately computed on the server side: the client only has float16, not enough for
    // a probe displayed to five decimals.
    void client
      .call<Readout | null>('app.readout', { x: point[0], y: point[1] })
      .then((result) => {
        const renderer = rendererRef.current;
        if (!renderer || !onStatus) return;
        onStatus({
          zoom: renderer.camera.zoom,
          cursor: { x: point[0], y: point[1] },
          values: result ? result.channels.map((c) => c.mean) : null,
          // The celestial part travels with the probe rather than through an RPC of its own: it
          // is a property of the same point, called at 30 Hz — a second round trip would double
          // the traffic.
          celestial: result?.celestial ?? null,
          precision: win.viewport.readout.precision,
          gpu: renderer.caps.renderer,
        });
      })
      .catch(() => undefined);
  };

  // --- interaction ----------------------------------------------------------
  const pointAt = (event: PointerEvent): readonly [number, number] | null => {
    const camera = rendererRef.current?.camera;
    return camera ? camera.viewportToImage([event.offsetX, event.offsetY]) : null;
  };

  const onPointerDown = (event: PointerEvent) => {
    if (event.button !== 0) return;
    const point = pointAt(event);
    if (!point) return;
    (event.currentTarget as HTMLCanvasElement).setPointerCapture(event.pointerId);

    switch (mode) {
      case 'pan':
        gestureRef.current = { kind: 'pan' };
        break;
      case 'zoom_in':
        void client.call('app.zoom_in', { pivot: [point[0], point[1]] }).catch(() => undefined);
        break;
      case 'zoom_out':
        void client.call('app.zoom_out', { pivot: [point[0], point[1]] }).catch(() => undefined);
        break;
      case 'center':
        void client
          .call('app.set_viewport', { center: [point[0], point[1]] })
          .catch(() => undefined);
        break;
      case 'new_preview':
        gestureRef.current = { kind: 'rubber', origin: point };
        setRubber([point[0], point[1], point[0], point[1]]);
        break;
      case 'edit_preview': {
        const target = viewAt(win.views, win.id, point[0], point[1]);
        if (target.rect) {
          gestureRef.current = {
            kind: 'move-preview',
            id: target.viewId,
            start: target.rect,
            grab: point,
          };
        }
        break;
      }
      case 'dynamic':
        // The tool is armed by a process panel (see dynamicTool.ts). Without it, this mode
        // existed on the domain side without a single click answering to it — that is what made
        // the DBE panel inoperative.
        dynamicTool.value?.onDown?.(toolEvent(event, point));
        break;
      default:
        // readout: nothing on click, everything happens on hover
        break;
    }
  };

  /** Tool event: the targeted view is the finest preview, as for a drop. */
  const toolEvent = (event: PointerEvent, point: readonly [number, number]): DynamicToolEvent => ({
    windowId: win.id,
    viewId: viewAt(win.views, win.id, point[0], point[1]).viewId,
    point,
    event,
  });

  const onPointerMove = (event: PointerEvent) => {
    const renderer = rendererRef.current;
    const point = pointAt(event);
    if (!renderer || !point) return;
    const gesture = gestureRef.current;

    if (gesture?.kind === 'pan') {
      renderer.camera.panByViewport(event.movementX, event.movementY);
      scheduleRender();
      return;
    }
    if (gesture?.kind === 'rubber') {
      setRubber([gesture.origin[0], gesture.origin[1], point[0], point[1]]);
      scheduleRender();
      return;
    }
    if (gesture?.kind === 'move-preview') {
      const dx = point[0] - gesture.grab[0];
      const dy = point[1] - gesture.grab[1];
      const [x0, y0, x1, y1] = gesture.start;
      setRubber([x0 + dx, y0 + dy, x1 + dx, y1 + dy]);
      scheduleRender();
      return;
    }

    if (mode === 'dynamic') {
      dynamicTool.value?.onMove?.(toolEvent(event, point));
      scheduleRender();
    }

    if (mode === 'readout') {
      setLoupe(point);
      probeReadout(point);
      scheduleRender();
    } else if (onStatus) {
      onStatus({
        zoom: renderer.camera.zoom,
        cursor: { x: point[0], y: point[1] },
        values: null,
        celestial: null,
        precision: win.viewport.readout.precision,
        gpu: renderer.caps.renderer,
      });
    }
  };

  const onPointerUp = (event: PointerEvent) => {
    const gesture = gestureRef.current;
    gestureRef.current = null;
    (event.currentTarget as HTMLCanvasElement).releasePointerCapture(event.pointerId);
    if (mode === 'dynamic') {
      const point = pointAt(event);
      if (point) dynamicTool.value?.onUp?.(toolEvent(event, point));
    }
    if (!gesture) return;

    if (gesture.kind === 'pan') {
      commitViewport();
      return;
    }

    const rect = stateRef.current.rubber;
    setRubber(null);
    scheduleRender();
    if (!rect) return;
    const [x0, y0, x1, y1] = normalise(rect);

    if (gesture.kind === 'rubber') {
      if (x1 - x0 < MIN_PREVIEW_PX || y1 - y0 < MIN_PREVIEW_PX) return; // a click, not a frame
      void client
        .call('app.new_preview', {
          x0: Math.round(x0), y0: Math.round(y0),
          x1: Math.round(x1), y1: Math.round(y1),
        })
        .catch((error: unknown) => console.error(error));
    } else {
      void client
        .call('app.modify_preview', {
          preview_id: gesture.id,
          x0: Math.round(x0), y0: Math.round(y0),
          x1: Math.round(x1), y1: Math.round(y1),
        })
        .catch((error: unknown) => console.error(error));
    }
  };

  const onPointerLeave = () => {
    if (loupe) {
      setLoupe(null);
      scheduleRender();
    }
  };

  const onWheel = (event: WheelEvent) => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    event.preventDefault();
    const pivot = renderer.camera.viewportToImage([event.offsetX, event.offsetY]);
    renderer.camera.setZoom(renderer.camera.zoom * (event.deltaY < 0 ? 1.25 : 0.8), pivot);
    scheduleRender();
    // The wheel has no end event: the gesture is considered finished after a silence.
    if (wheelRef.current !== null) globalThis.clearTimeout(wheelRef.current);
    wheelRef.current = globalThis.setTimeout(() => {
      wheelRef.current = null;
      commitViewport();
    }, WHEEL_SETTLE_MS);
  };

  // --- A/B toggle -----------------------------------------------------------
  // The memory and the gesture live in `./ab`: the palette command must be able to
  // toggle without the viewport having focus.
  // --- dropping of instances and files ---------------------------------------
  const onDragOver = (event: DragEvent) => {
    const transfer = event.dataTransfer;
    const renderer = rendererRef.current;
    if (!transfer || !renderer) return;
    // A **file** gets opened: it does not target any particular view, so no drop
    // rectangle is drawn — the cursor is enough to say that the release is accepted. Making
    // it aim at a preview would suggest that it will be applied to that preview.
    if (carriesFile(transfer)) {
      event.preventDefault();
      transfer.dropEffect = 'copy';
      if (stateRef.current.dropTarget) {
        setDropTarget(null);
        scheduleRender();
      }
      return;
    }
    if (!carriesAnything(transfer)) return;
    event.preventDefault();
    const legal = carriesApplicable(transfer);
    transfer.dropEffect = legal ? 'copy' : 'none';
    const point = renderer.camera.viewportToImage([event.offsetX, event.offsetY]);
    const current = stateRef.current.win;
    setDropTarget({ ...viewAt(current.views, current.id, point[0], point[1]), legal });
    scheduleRender();
  };

  const onDragLeave = () => {
    setDropTarget(null);
    scheduleRender();
  };

  const onDrop = (event: DragEvent) => {
    const transfer = event.dataTransfer;
    const target = stateRef.current.dropTarget;
    setDropTarget(null);
    scheduleRender();
    if (!transfer) return;

    // A dropped file gets opened — `app.open`, hence echoed, exactly like a double click
    // in the explorer or a line typed in the console.
    const path = carriesFile(transfer) ? readFilePath(transfer) : null;
    if (path) {
      event.preventDefault();
      // A project replaces the whole session: it is `openProject` that decides, and that asks
      // first if some work is unsaved.
      if (path.toLowerCase().endsWith('.retina')) {
        void openProject(path).catch((error: unknown) => console.error(error));
        return;
      }
      void client.call('app.open', { path }).catch((error: unknown) => console.error(error));
      return;
    }

    if (!target?.legal) return;
    event.preventDefault();
    const payload = readDragPayload(transfer);
    if (!payload) return;
    // A recipe leaves as **one** ordered job: a loop of `process.run` would release N concurrent
    // jobs onto a pool of four threads, and the order is the very meaning of a pipeline.
    if (payload.kind === 'container') {
      void runContainer(payload.processes, target.viewId, payload.name).catch(
        (error: unknown) => console.error(error),
      );
      return;
    }
    for (const process of payload.processes) {
      void runProcess(process.process_id, process.values, target.viewId).catch(
        (error: unknown) => console.error(error),
      );
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <ViewportToolbar window={win} />
      <Breadcrumb window={win} view={view} />
      <div
        style={{ position: 'relative', flex: 1, minHeight: 0 }}
        tabIndex={0}
        data-focus-ring
        title={m.viewport_compare_hint()}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        <canvas
          ref={canvasRef}
          style={{
            display: 'block',
            width: '100%',
            height: '100%',
            background: 'var(--retina-viewport-background)',
            cursor: (mode === 'dynamic' ? tool?.cursor : undefined) ?? CURSORS[mode] ?? 'default',
            touchAction: 'none',
          }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onPointerLeave={onPointerLeave}
          onWheel={onWheel}
        />
        <canvas
          ref={overlayRef}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            pointerEvents: 'none',
          }}
        />
      </div>
    </div>
  );
}

const CURSORS: Record<string, string> = {
  readout: 'crosshair',
  pan: 'grab',
  zoom_in: 'zoom-in',
  zoom_out: 'zoom-out',
  center: 'crosshair',
  new_preview: 'crosshair',
  edit_preview: 'move',
  // A dynamic tool may propose its own (see DynamicTool.cursor); failing that, the crosshair at
  // least says that the click will do something.
  dynamic: 'crosshair',
};

function normalise(rect: Rect): Rect {
  return [
    Math.min(rect[0], rect[2]),
    Math.min(rect[1], rect[3]),
    Math.max(rect[0], rect[2]),
    Math.max(rect[1], rect[3]),
  ];
}
