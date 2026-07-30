// Shared histogram — the distribution of the pixels, and what a transformation does to it.
//
// # Two choices carried over from the STF panel
//
// **Counts on a logarithmic scale.** On a linear exposure, the sky background holds 99% of the
// pixels within the first hundredth of the range: on a linear scale, the curve is a spike
// against the axis and everything else is flat.
//
// **Linear abscissa.** The X axis stays the raw input value: the markers land where the data
// actually is.
//
// # Why the histogram of the result is computed here, and not asked of the server again
//
// The server computes the histogram of the **pixels**, which a tone curve being edited has not
// touched yet: asking for it again on every handle movement would return exactly the same
// answer (it is even cached by `(view, generation, bins)`). What one wants to see, however, is
// the distribution *after* transformation.
//
// A tone transformation is a monotonic point operation: it **moves** the histogram's columns
// without changing their populations. It can therefore be computed exactly from the original
// histogram, without reading a pixel or making a round trip — instantaneous instead of
// debounced, and correct by construction.
//
// The debounce serves elsewhere: absorbing bursts of *pixel changes* (repeated undo/redo, a
// process applied in a loop), where each generation would otherwise trigger a full computation
// over the whole image.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import { fillBackground, prepare, token } from './canvas';

/** Same value as the real-time preview debounce: the same eye/machine trade-off. */
const DEBOUNCE_MS = 250;

export interface HistogramChannel {
  counts: number[];
  median: number;
  madn: number;
  min: number;
  max: number;
}

export interface HistogramData {
  bins: number;
  channels: HistogramChannel[];
}

/** A tone transformation to visualize: `x` in [0,1] → `y` in [0,1]. */
export type Transfer = (x: number) => number;

/**
 * The histogram of the view, reloaded when its **pixels** change.
 *
 * Debounced: a burst of generations (chained undo/redo, a process applied several times) must
 * trigger a single computation, not one per intermediate state nobody will have seen.
 */
export function useHistogram(
  viewId: string | undefined,
  pixelGen: number | undefined,
  bins = 256,
): HistogramData | null {
  const [data, setData] = useState<HistogramData | null>(null);

  useEffect(() => {
    if (!viewId) {
      setData(null);
      return;
    }
    let annule = false;
    const timer = window.setTimeout(() => {
      void client
        .call<HistogramData>('stats.histogram', { view: viewId, bins })
        .then((result) => {
          if (!annule) setData(result);
        })
        .catch(() => undefined);
    }, DEBOUNCE_MS);
    return () => {
      annule = true;
      window.clearTimeout(timer);
    };
  }, [viewId, pixelGen, bins]);

  return data;
}

/**
 * Redistributes the counts through a monotonic transformation.
 *
 * Exact, not approximate: a point operation neither creates nor destroys a pixel, it only moves
 * the column it is counted in. Two source columns may land in the same one (the transformation
 * compresses that region) — which is precisely what one wants to see.
 */
export function remap(counts: readonly number[], transfer: Transfer): number[] {
  const out = new Array<number>(counts.length).fill(0);
  const dernier = counts.length - 1;
  counts.forEach((count, i) => {
    if (!count) return;
    const y = transfer((i + 0.5) / counts.length);
    const cible = Math.min(Math.max(Math.round(y * dernier), 0), dernier);
    out[cible]! += count;
  });
  return out;
}

/** Per-channel colors — RGB when there are three, gray otherwise. */
function colours(count: number): string[] {
  return count >= 3
    ? ['rgba(255,90,90,0.55)', 'rgba(90,220,120,0.55)', 'rgba(90,150,255,0.55)']
    : ['rgba(170,170,200,0.6)'];
}

/**
 * Draws series of counts across the full width, in log1p.
 *
 * The maximum is taken over **all** channels: scaling them separately would make an empty
 * channel look as tall as a saturated one.
 */
export function drawCounts(
  ctx: CanvasRenderingContext2D,
  series: readonly (readonly number[])[],
  width: number,
  height: number,
  alpha = 1,
): void {
  let peak = 1;
  for (const counts of series) for (const n of counts) peak = Math.max(peak, Math.log1p(n));
  const palette = colours(series.length);
  ctx.save();
  ctx.globalAlpha = alpha;
  series.forEach((counts, index) => {
    ctx.beginPath();
    ctx.moveTo(0, height);
    counts.forEach((count, i) => {
      const x = (i / Math.max(counts.length - 1, 1)) * width;
      ctx.lineTo(x, height - (Math.log1p(count) / peak) * (height - 4));
    });
    ctx.lineTo(width, height);
    ctx.closePath();
    ctx.fillStyle = palette[Math.min(index, palette.length - 1)] ?? palette[0]!;
    ctx.fill();
  });
  ctx.restore();
}

interface Props {
  data: HistogramData | null;
  /** Transformation being edited: its curve and the resulting histogram. */
  transfer?: Transfer;
  height?: number;
}

/** What the hover reveals: the value pointed at and the population of its column. */
interface Hover {
  value: number;
  counts: number[];
}

export function Histogram({ data, transfer, height = 120 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const surface = prepare(canvas, height);
    if (!surface) return;
    const { ctx, width, height: h } = surface;
    fillBackground(surface);

    if (data?.channels.length) {
      const brut = data.channels.map((c) => c.counts);
      // The original faded in the background, the result on top: one sees *what the
      // transformation moves*, which neither curve alone shows.
      if (transfer) {
        drawCounts(ctx, brut, width, h, 0.25);
        drawCounts(ctx, brut.map((counts) => remap(counts, transfer)), width, h);
      } else {
        drawCounts(ctx, brut, width, h);
      }
    }

    if (transfer) {
      ctx.beginPath();
      for (let i = 0; i <= 128; i++) {
        const x = i / 128;
        const y = Math.min(Math.max(transfer(x), 0), 1);
        const px = x * width;
        const py = h - y * (h - 4);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.strokeStyle = token('--vscode-charts-green', '#4ec9b0');
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    if (hover) {
      const x = hover.value * width;
      ctx.strokeStyle = token('--vscode-focusBorder', '#007fd4');
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
  }, [data, transfer, hover, height]);

  const onMove = (event: PointerEvent) => {
    const canvas = event.currentTarget as HTMLCanvasElement;
    const value = Math.min(Math.max(event.offsetX / canvas.clientWidth, 0), 1);
    const canaux = data?.channels ?? [];
    const bin = canaux.length
      ? Math.min(Math.round(value * (canaux[0]!.counts.length - 1)), canaux[0]!.counts.length - 1)
      : 0;
    setHover({ value, counts: canaux.map((c) => c.counts[bin] ?? 0) });
  };

  return (
    <div style={{ display: 'grid', gap: '2px' }}>
      <canvas
        ref={canvasRef}
        aria-label={m.histogram_label()}
        style={{ width: '100%', height: `${height}px`, touchAction: 'none' }}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      />
      <div
        style={{
          font: '11px var(--retina-font-mono)',
          color: 'var(--vscode-descriptionForeground)',
          minHeight: '14px',
        }}
      >
        {hover
          ? `${hover.value.toFixed(5)}${transfer ? ` → ${transfer(hover.value).toFixed(5)}` : ''}`
            + ` · ${hover.counts.join(' / ')} px`
          : data
            ? m.histogram_summary({
                median: data.channels[0]?.median.toFixed(5) ?? '—',
                madn: data.channels[0]?.madn.toFixed(5) ?? '—',
              })
            : m.histogram_no_data()}
      </div>
    </div>
  );
}
