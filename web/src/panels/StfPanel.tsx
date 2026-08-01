// STF panel: histogram and three handles, as in the old Qt shell.
//
// # Two decisions carried over from the existing implementation
//
// **Counts on a logarithmic scale.** On a linear exposure, the sky background accounts for
// 99 % of the pixels within the first hundredth of the range: on a linear scale, the curve is
// a spike against the axis and the rest is flat. The log makes the highlights readable
// without hiding the background.
//
// **Linear abscissa.** The X axis stays the raw input value, with no stretch: the handles sit
// where the data actually is, and the position of `shadows` means something.
//
// The transfer curve is plotted by the same function as the shader (`applyChannelStf`): what
// is drawn cannot diverge from what is displayed.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import { activeView, activeWindow, stfIsVisible } from '../state/store';
import { fillBackground, prepare, token } from '../ui/canvas';
import { drawCounts, useHistogram } from '../ui/Histogram';
import { applyChannelStf } from '../viewport/shaders';

type Handle = 'shadows' | 'midtones' | 'highlights';

const HANDLE_TOKEN: Record<Handle, string> = {
  shadows: '--retina-stf-shadows',
  midtones: '--retina-stf-midtones',
  highlights: '--retina-stf-highlights',
};

const HEIGHT = 150;

export function StfPanel() {
  const view = activeView.value;
  const win = activeWindow.value;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragRef = useRef<Handle | null>(null);
  /** Hovered value — the histogram's readout probe. */
  const [hover, setHover] = useState<number | null>(null);

  const channel = view?.stf.channels[0] ?? { shadows: 0, midtones: 0.5, highlights: 1 };

  // Reloaded when the **pixels** change — the STF itself does not touch them. The hook
  // debounces: a burst of generations must not trigger one computation per intermediate
  // state that nobody will have seen.
  const histogram = useHistogram(view?.id, view?.pixel_gen);

  useEffect(() => {
    draw();
  }, [histogram, view?.stf, hover]);

  function draw(): void {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const surface = prepare(canvas, HEIGHT);
    if (!surface) return;
    const { ctx, width: w, height: h } = surface;
    fillBackground(surface);

    if (histogram) {
      // log1p and a scale shared by every channel: see the header of `ui/Histogram`.
      drawCounts(ctx, histogram.channels.map((c) => c.counts), w, h);
    }

    // Transfer curve — the same function as the shader.
    ctx.beginPath();
    for (let i = 0; i <= 128; i++) {
      const x = i / 128;
      const y = applyChannelStf(x, channel.shadows, channel.midtones, channel.highlights);
      const px = x * w;
      const py = h - y * (h - 4);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.strokeStyle = token('--vscode-charts-green', '#4ec9b0');
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Handles. `midtones` is a parameter normalised within [shadows, highlights]: it is drawn
    // at its real input position, otherwise it "jumps" whenever shadows is moved.
    const span = Math.max(channel.highlights - channel.shadows, 1e-6);
    const positions: Array<[Handle, number]> = [
      ['shadows', channel.shadows],
      ['midtones', channel.shadows + channel.midtones * span],
      ['highlights', channel.highlights],
    ];
    for (const [handle, value] of positions) {
      const x = Math.min(Math.max(value, 0), 1) * w;
      ctx.strokeStyle = token(HANDLE_TOKEN[handle], '#ffffff');
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
      ctx.fillStyle = ctx.strokeStyle;
      ctx.beginPath();
      ctx.moveTo(x, h - 8);
      ctx.lineTo(x - 5, h);
      ctx.lineTo(x + 5, h);
      ctx.closePath();
      ctx.fill();
    }

    if (hover !== null) {
      ctx.strokeStyle = token('--vscode-focusBorder', '#007fd4');
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(hover * w, 0);
      ctx.lineTo(hover * w, h);
      ctx.stroke();
    }
  }

  /** Counts of the hovered column — the histogram's readout probe. */
  function countsAt(value: number): number[] {
    const canaux = histogram?.channels ?? [];
    if (!canaux.length) return [];
    const bins = canaux[0]!.counts.length;
    const bin = Math.min(Math.max(Math.round(value * (bins - 1)), 0), bins - 1);
    return canaux.map((c) => c.counts[bin] ?? 0);
  }

  function handleAt(x: number, width: number): Handle {
    const span = Math.max(channel.highlights - channel.shadows, 1e-6);
    const value = x / width;
    const candidates: Array<[Handle, number]> = [
      ['shadows', channel.shadows],
      ['midtones', channel.shadows + channel.midtones * span],
      ['highlights', channel.highlights],
    ];
    let best: Handle = 'midtones';
    let bestDistance = Infinity;
    for (const [handle, position] of candidates) {
      const distance = Math.abs(position - value);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = handle;
      }
    }
    return best;
  }

  function commit(handle: Handle, rawValue: number): void {
    if (!view) return;
    const value = Math.min(Math.max(rawValue, 0), 1);
    let { shadows, midtones, highlights } = channel;

    if (handle === 'shadows') {
      shadows = Math.min(value, highlights - 1e-4);
    } else if (handle === 'highlights') {
      highlights = Math.max(value, shadows + 1e-4);
    } else {
      // What is grabbed is an input value; the domain expects a normalised midtones.
      const span = Math.max(highlights - shadows, 1e-6);
      midtones = Math.min(Math.max((value - shadows) / span, 0), 1);
    }

    const count = Math.max(1, view.stf.channels.length);
    void client
      .call('app.set_stf', {
        channels: Array.from({ length: count }, () => ({ shadows, midtones, highlights })),
      })
      .catch((error: unknown) => console.error(error));
  }

  const onPointerDown = (event: PointerEvent) => {
    const canvas = event.currentTarget as HTMLCanvasElement;
    canvas.setPointerCapture(event.pointerId);
    dragRef.current = handleAt(event.offsetX, canvas.clientWidth);
    commit(dragRef.current, event.offsetX / canvas.clientWidth);
  };

  const onPointerMove = (event: PointerEvent) => {
    const canvas = event.currentTarget as HTMLCanvasElement;
    const value = Math.min(Math.max(event.offsetX / canvas.clientWidth, 0), 1);
    setHover(value);
    if (!dragRef.current) return;
    commit(dragRef.current, value);
  };

  const onPointerUp = (event: PointerEvent) => {
    dragRef.current = null;
    (event.currentTarget as HTMLCanvasElement).releasePointerCapture(event.pointerId);
  };

  if (!view || !win) {
    return (
      <p style={{ color: 'var(--vscode-descriptionForeground)', padding: '8px 12px' }}>
        {m.panels_no_active_view()}
      </p>
    );
  }

  const stfMoves = stfIsVisible(view);

  const button = {
    background: 'var(--vscode-button-secondaryBackground)',
    color: 'var(--vscode-button-secondaryForeground)',
    border: 'none',
    borderRadius: '2px',
    padding: '4px 10px',
    font: '12px var(--retina-font-ui)',
    cursor: 'pointer',
  } as const;

  return (
    <div style={{ padding: '4px 8px', display: 'grid', gap: '8px' }}>
      <canvas
        ref={canvasRef}
        style={{ width: '100%', height: `${HEIGHT}px`, cursor: 'ew-resize', touchAction: 'none' }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={() => setHover(null)}
      />
      {hover !== null && (
        <div
          style={{
            font: '11px var(--retina-font-mono)',
            color: 'var(--vscode-descriptionForeground)',
          }}
        >
          {hover.toFixed(5)} → {applyChannelStf(
            hover, channel.shadows, channel.midtones, channel.highlights,
          ).toFixed(5)}
          {countsAt(hover).length > 0 && ` · ${countsAt(hover).join(' / ')} px`}
        </div>
      )}
      <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
        <button
          style={button}
          title={m.panel_stf_auto_tip()}
          onClick={() => void client.call('app.compute_auto_stf').catch(() => undefined)}
        >
          {m.panel_stf_auto()}
        </button>
        <button
          style={button}
          onClick={() => {
            void client
              .call('app.set_stf', {
                channels: view.stf.channels.map(() => ({
                  shadows: 0,
                  midtones: 0.5,
                  highlights: 1,
                })),
              })
              .catch(() => undefined);
          }}
        >
          {m.process_reset()}
        </button>
        {/* The step from "the display is right" to "the image is right". Without it the three
            values had to be read here and typed back into a HistogramTransformation form —
            the domain has known how to build that process from an STF all along, and nothing
            called it. Disabled on the identity: baking it would push a history entry that
            changes nothing.

            "Apply to pixels" and not "Apply": a process form's own button is already called
            that, and next to Auto/Reset the bare verb does not say apply *what*, nor that it
            is the one gesture here that touches the image. */}
        <button
          style={button}
          title={m.panel_stf_apply_tip()}
          disabled={!stfMoves}
          onClick={() => void client.call('app.apply_stf').catch(() => undefined)}
        >
          {m.panel_stf_apply()}
        </button>
        <label
          style={{ display: 'flex', gap: '4px', alignItems: 'center', fontSize: '12px' }}
        >
          <input
            type="checkbox"
            checked={win.viewport.stf_enabled}
            onChange={(event) =>
              void client
                .call('app.set_stf_enabled', {
                  enabled: (event.target as HTMLInputElement).checked,
                })
                .catch(() => undefined)
            }
          />
          {m.panel_stf_enabled()}
        </label>
      </div>
      <div
        style={{
          font: '11px var(--retina-font-mono)',
          color: 'var(--vscode-descriptionForeground)',
        }}
      >
        <span style={{ color: token('--retina-stf-shadows', '#4a9eff') }}>
          {m.panel_stf_shadows()} {channel.shadows.toFixed(5)}
        </span>{' '}
        <span style={{ color: token('--retina-stf-midtones', '#4ec9b0') }}>
          {m.panel_stf_midtones()} {channel.midtones.toFixed(5)}
        </span>{' '}
        <span style={{ color: token('--retina-stf-highlights', '#ff6a6a') }}>
          {m.panel_stf_highlights()} {channel.highlights.toFixed(5)}
        </span>
      </div>
    </div>
  );
}
