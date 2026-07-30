// Real-time preview panel, shown **next to** the viewport.
//
// [RETHOUGHT vs the Qt shell] There the preview occupied a bottom dock, under the console —
// yet it is a before/after comparison: its place is against the image, not elsewhere. Here it
// is a panel of the centre zone, adjacent to the viewport.
//
// It reuses the same WebGL2 renderer: same shaders, same analytic STF. Comparing the before
// and the after would make no sense if the two images did not go through the same display
// path.

import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import { viewById } from '../state/store';
import { ViewportRenderer } from '../viewport/renderer';
import { glEpoch } from '../viewport/sharedGL';
import { levelDims, needsTiling, overviewKey, overviewScale, tileCap } from '../viewport/tiles';
import { rtpErrors, rtpFrames } from './rtp';

export function RtpPanel({ owner }: { owner: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<ViewportRenderer | null>(null);
  const loadedRef = useRef(0);
  /** Curtain mode: right of the handle, the original image; left of it, the preview. */
  const [curtain, setCurtain] = useState(false);
  const [split, setSplit] = useState(0.5);

  const frame = rtpFrames.value[owner] ?? null;
  // The PREVIEW's view, not the active view: the form may have followed the user elsewhere
  // during the computation, and rendering the curtain against another image would compare two
  // different things without saying so. `null` = the view has been closed since.
  const located = frame ? viewById(frame.view) : null;
  const view = located?.view ?? null;
  const win = located?.win ?? null;

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let renderer: ViewportRenderer;
    try {
      renderer = new ViewportRenderer(canvas, `rtp:${owner}`);
    } catch (error) {
      console.error(error);
      return;
    }
    rendererRef.current = renderer;
    renderer.render();
    // Incidentally, this panel's historical defect: nothing redrew on resize (the renderer
    // only measured its size at render time, which was never triggered). The observer also
    // settles tab reactivation: a hidden dockview panel has a zero-sized canvas, and taking
    // back a non-zero size re-triggers the observation.
    const observer = new ResizeObserver(() => renderer.render());
    observer.observe(canvas);
    return () => {
      observer.disconnect();
      renderer.dispose();
      rendererRef.current = null;
    };
  }, [owner]);

  // GL context restoration: forget what we thought was loaded, the next effect will refetch.
  useEffect(() => {
    if (glEpoch.value === 0) return;
    loadedRef.current = 0;
  }, [glEpoch.value]);

  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer || !frame) return;
    const key = `rtp:${frame.generation}`;
    // Resume without a transfer if the texture is still there — and re-fetch otherwise, even
    // at an unchanged generation: it may have been evicted while the panel was hidden.
    if (loadedRef.current === frame.generation && renderer.select(key)) {
      renderer.camera.zoomToFit(true);
      renderer.render();
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const response = await client.fetch(`/api/rtp.f16?gen=${frame.generation}`);
        if (response.status === 409) return; // a more recent request has already gone through
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const buffer = await response.arrayBuffer();
        // Freshness judged against the SOURCE OF TRUTH, not against the renderer's identity:
        // a more recent generation may have been published during the transfer.
        if (cancelled || rtpFrames.value[owner]?.generation !== frame.generation) return;
        // The quad is that of the **source**, not of the texture: the preview is decimated,
        // and it must cover exactly the image it represents — without which the curtain
        // would compare two different scales.
        renderer.uploadImage(
          buffer,
          { width: frame.width, height: frame.height, channels: frame.channels },
          key,
          view ? [view.width, view.height] : undefined,
        );
        loadedRef.current = frame.generation;
        renderer.camera.zoomToFit(true);
        renderer.render();
      } catch (error) {
        console.error('preview', error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [frame?.generation, view?.width, view?.height, glEpoch.value]);

  // --- before/after curtain --------------------------------------------------
  //
  // The original is only loaded if the comparison is asked for: it is a full-resolution
  // transfer, and paying for it upfront for a mode nobody uses would be absurd. Once there,
  // it stays in the texture cache — dragging the handle then costs nothing.
  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    if (!curtain || !view || !frame) {
      renderer.curtain = null;
      renderer.render();
      return;
    }
    // The same key as the view's viewport: from the GLOBAL cache, the full-resolution texture
    // is almost always already there — the neighbouring viewport paid for it. The `orig:` key
    // from before the shared context kept a SECOND GPU copy of it.
    // View beyond the texture cap: the "before" is the pyramid's overview (same key as the
    // tiled viewport), uploaded with the source's quad — like the decimated preview.
    const cap = tileCap(renderer.caps.maxTextureSize);
    const paved = needsTiling(view.width, view.height, cap);
    const scale = paved ? overviewScale(view.width, view.height, cap) : 1;
    const key = paved
      ? overviewKey(view.id, view.pixel_gen, scale)
      : `${view.id}:${view.pixel_gen}`;
    const armer = () => {
      renderer.select(`rtp:${frame.generation}`);
      renderer.curtain = { key, split };
      renderer.render();
    };
    if (renderer.hasCached(key)) {
      armer();
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const response = await client.fetch(
          `/api/pixels/${encodeURIComponent(view.id)}.f16?gen=${view.pixel_gen}` +
            (paved ? `&scale=${scale}` : ''),
        );
        if (!response.ok) return;
        const buffer = await response.arrayBuffer();
        if (cancelled || viewById(view.id)?.view.pixel_gen !== view.pixel_gen) return;
        const [w, h] = levelDims(view.width, view.height, scale);
        renderer.uploadImage(
          buffer,
          { width: w, height: h, channels: view.channels },
          key,
          paved ? [view.width, view.height] : undefined,
        );
        armer();
      } catch (error) {
        console.error('before/after curtain', error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [curtain, split, view?.id, view?.pixel_gen, frame?.generation]);

  // The preview's STF follows the view's: without that, a preview of linear data would appear
  // black next to a stretched image, and the comparison would be unusable.
  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer || !view || !win) return;
    renderer.stfEnabled = view.stf.enabled && win.viewport.stf_enabled;
    if (view.stf.channels.length > 0) renderer.stfChannels = view.stf.channels;
    renderer.channel = win.viewport.channel;
    renderer.render();
  }, [view?.stf, win?.viewport.channel, win?.viewport.stf_enabled, frame?.generation]);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: 'var(--retina-viewport-background)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '2px 8px',
          fontSize: '11px',
          fontFamily: 'var(--retina-font-mono)',
          color: 'var(--vscode-descriptionForeground)',
          borderBottom: '1px solid var(--vscode-panel-border)',
        }}
      >
        <span>{owner || m.rtp_preview()}</span>
        {frame && (
          <span>
            {/* The view id is a domain identifier: it is not translated. It is displayed
                because the preview may carry a view other than the active one — which is
                precisely what "Track view" lets one decide. */}
            {frame.view} · {frame.width}×{frame.height} ·{' '}
            {Math.round(frame.seconds * 1000)} ms · {m.rtp_decimated()}
            {!view && ` · ${m.rtp_view_gone()}`}
          </span>
        )}
        {rtpErrors.value[owner] && (
          <span style={{ color: 'var(--vscode-errorForeground)' }}>{rtpErrors.value[owner]}</span>
        )}
        <span style={{ flex: 1 }} />
        <label
          style={{ display: 'flex', gap: '4px', alignItems: 'center', cursor: 'pointer' }}
          title={m.rtp_curtain_tip()}
        >
          <input
            type="checkbox"
            checked={curtain}
            disabled={!frame}
            onChange={(e) => setCurtain((e.target as HTMLInputElement).checked)}
          />
          {m.rtp_curtain()}
        </label>
        {curtain && frame && (
          <input
            type="range"
            min={0}
            max={1}
            step={0.005}
            value={split}
            aria-label={m.rtp_curtain_position()}
            style={{ width: '90px' }}
            onInput={(e) => setSplit(Number((e.target as HTMLInputElement).value))}
          />
        )}
      </div>
      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        <canvas ref={canvasRef} style={{ display: 'block', width: '100%', height: '100%' }} />
        {!frame && !rtpErrors.value[owner] && (
          <p
            style={{
              position: 'absolute',
              inset: 0,
              display: 'grid',
              placeContent: 'center',
              color: 'var(--vscode-descriptionForeground)',
              fontSize: '12px',
              margin: 0,
            }}
          >
            {m.rtp_empty()}
          </p>
        )}
      </div>
    </div>
  );
}
