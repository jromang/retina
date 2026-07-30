// PCHIP curve editor — the field of the ``points`` parameter (CurvesTransformation).
//
// # Why PCHIP and not a classic spline
//
// Cubic Hermite interpolation **preserves monotonicity**: a transfer curve whose control
// points rise will never dip back down between two points. A natural spline, on the other
// hand, produces overshoots — on a tone curve, that shows up immediately as local contrast
// inversions. It is the same reason that made PCHIP the choice on the domain side
// (``processes/curves.py::_pchip``), and the implementation here mirrors it: the plot must
// show what the computation will do.

import { useEffect, useRef, useState } from 'preact/hooks';

import { fillBackground, prepare, token } from '../ui/canvas';
import type { FieldProps } from './fields';
import { m } from '../paraglide/messages';

const HEIGHT = 200;
const HIT_RADIUS = 0.035; // in normalised coordinates

type Point = [number, number];

/**
 * Monotonicity-preserving Hermite interpolation (Fritsch–Carlson).
 *
 * Port of ``processes/curves.py::_pchip``: the slopes at the knots are bounded so that no
 * segment can overshoot its endpoints.
 */
export function pchip(points: readonly Point[], x: number): number {
  const n = points.length;
  if (n === 0) return x;
  if (n === 1) return points[0]![1];
  if (x <= points[0]![0]) return points[0]![1];
  if (x >= points[n - 1]![0]) return points[n - 1]![1];

  // secant slopes
  const h: number[] = [];
  const delta: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    const dx = points[i + 1]![0] - points[i]![0];
    h.push(dx);
    delta.push(dx === 0 ? 0 : (points[i + 1]![1] - points[i]![1]) / dx);
  }

  // slopes at the knots, bounded so as to stay monotone
  const m: number[] = new Array(n).fill(0);
  m[0] = delta[0]!;
  m[n - 1] = delta[n - 2]!;
  for (let i = 1; i < n - 1; i++) {
    const d0 = delta[i - 1]!;
    const d1 = delta[i]!;
    if (d0 * d1 <= 0) {
      m[i] = 0; // local extremum: zero slope, otherwise the curve overshoots
    } else {
      const w1 = 2 * h[i]! + h[i - 1]!;
      const w2 = h[i]! + 2 * h[i - 1]!;
      m[i] = (w1 + w2) / (w1 / d0 + w2 / d1);
    }
  }

  let k = 0;
  while (k < n - 2 && x > points[k + 1]![0]) k++;
  const t = (x - points[k]![0]) / h[k]!;
  const t2 = t * t;
  const t3 = t2 * t;
  return (
    (2 * t3 - 3 * t2 + 1) * points[k]![1] +
    (t3 - 2 * t2 + t) * h[k]! * m[k]! +
    (-2 * t3 + 3 * t2) * points[k + 1]![1] +
    (t3 - t2) * h[k]! * m[k + 1]!
  );
}

export function CurveEditor({ param, value, onChange }: FieldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  const points: Point[] = Array.isArray(value) && value.length >= 2
    ? (value as Point[]).map((p) => [Number(p[0]), Number(p[1])])
    : [[0, 0], [1, 1]];

  useEffect(draw, [value]);

  function draw(): void {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const surface = prepare(canvas, HEIGHT);
    if (!surface) return;
    const { ctx, width: w } = surface;
    fillBackground(surface);

    // identity diagonal, visual reference for "no change"
    ctx.strokeStyle = '#555555';
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(0, HEIGHT);
    ctx.lineTo(w, 0);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.beginPath();
    for (let i = 0; i <= 200; i++) {
      const x = i / 200;
      const y = Math.min(Math.max(pchip(points, x), 0), 1);
      const px = x * w;
      const py = HEIGHT - y * HEIGHT;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.strokeStyle = token('--vscode-charts-green', '#4ec9b0');
    ctx.lineWidth = 1.5;
    ctx.stroke();

    for (const [x, y] of points) {
      ctx.beginPath();
      ctx.arc(x * w, HEIGHT - y * HEIGHT, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = token('--vscode-charts-yellow', '#dcdcaa');
      ctx.fill();
    }
  }

  const at = (event: PointerEvent): Point => {
    const canvas = event.currentTarget as HTMLCanvasElement;
    return [
      Math.min(Math.max(event.offsetX / canvas.clientWidth, 0), 1),
      Math.min(Math.max(1 - event.offsetY / HEIGHT, 0), 1),
    ];
  };

  const nearest = (point: Point): number | null => {
    let best: number | null = null;
    let bestDistance = HIT_RADIUS;
    points.forEach(([x, y], index) => {
      const distance = Math.hypot(x - point[0], y - point[1]);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = index;
      }
    });
    return best;
  };

  /** Sorts and clamps — the visual order stays coherent whatever one does. */
  const commit = (next: Point[]) => {
    const sorted = [...next]
      .map(([x, y]): Point => [Math.min(Math.max(x, 0), 1), Math.min(Math.max(y, 0), 1)])
      .sort((a, b) => a[0] - b[0]);
    onChange(sorted);
  };

  return (
    <div style={{ display: 'grid', gap: '3px' }}>
      <canvas
        ref={canvasRef}
        title={`${param.tooltip}\n${m.curve_editor_hint()}`}
        style={{ width: '100%', height: `${HEIGHT}px`, cursor: 'crosshair', touchAction: 'none' }}
        onPointerDown={(event) => {
          const point = at(event as PointerEvent);
          const index = nearest(point);
          if (index !== null) {
            setDragIndex(index);
            (event.currentTarget as HTMLCanvasElement).setPointerCapture(
              (event as PointerEvent).pointerId,
            );
          }
        }}
        onPointerMove={(event) => {
          if (dragIndex === null) return;
          const point = at(event as PointerEvent);
          const next = [...points];
          next[dragIndex] = point;
          commit(next);
        }}
        onPointerUp={(event) => {
          setDragIndex(null);
          (event.currentTarget as HTMLCanvasElement).releasePointerCapture(
            (event as PointerEvent).pointerId,
          );
        }}
        onDblClick={(event) => commit([...points, at(event as unknown as PointerEvent)])}
        onContextMenu={(event) => {
          event.preventDefault();
          // Two points minimum: a curve needs a start and an end.
          if (points.length <= 2) return;
          const index = nearest(at(event as unknown as PointerEvent));
          if (index !== null) commit(points.filter((_, i) => i !== index));
        }}
      />
      <button
        onClick={() => commit([[0, 0], [1, 1]])}
        style={{
          justifySelf: 'start',
          background: 'var(--vscode-button-secondaryBackground)',
          color: 'var(--vscode-button-secondaryForeground)',
          border: 'none',
          borderRadius: '2px',
          padding: '2px 8px',
          fontSize: '11px',
          cursor: 'pointer',
        }}
      >
        {m.curve_editor_reset()}
      </button>
    </div>
  );
}
