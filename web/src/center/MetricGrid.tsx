// Grid of metric charts — one exposure = one point.
//
// The reference application bundles gnuplot for this screen; the web has no need of it. What
// is being drawn is six scatter plots of a few dozen samples: ten lines of 2D canvas, against
// a charting dependency whose weight would be paid at every load.
//
// What the charts bring that the table does not: the **shape** of the batch. A focus drift
// over the night shows up as a slope; a cloudy spell as a dip over three consecutive points.
// No sorted column shows that.
//
// Clicking a point selects the frame (it is highlighted in the table); double-clicking opens
// it in the viewport — the same gesture as in the table, because a double-click that opened
// here and dropped there would be a trap. Dropping remains the table's checkbox, or the space
// bar: a destructive gesture is not triggered by a double-click on a scatter plot.

import { useEffect, useRef } from 'preact/hooks';

import {
  METRICS,
  type Measurement,
  type Metric,
  basename,
  metricRange,
  openFrame,
  referenceFrame,
  rows,
  selectedFrame,
} from '../pipeline/selector';
import { m } from '../paraglide/messages';
import { fillBackground, prepare, scale, token } from '../ui/canvas';

const HEIGHT = 110;
const PADDING = { left: 6, right: 6, top: 8, bottom: 8 };
const RADIUS = 3.5;

const LABEL: Record<Metric, string> = {
  fwhm: m.metric_fwhm(),
  eccentricity: m.metric_eccentricity(),
  snr: m.metric_snr(),
  stars: m.metric_stars(),
  noise: m.metric_noise(),
  median: m.metric_median(),
};

/** Abscissa of a point: its rank in the batch, spread over the usable width. */
function pointX(index: number, count: number, width: number): number {
  const gauche = PADDING.left + RADIUS;
  const droite = width - PADDING.right - RADIUS;
  if (count <= 1) return (gauche + droite) / 2;
  return scale(index, [0, count - 1], [gauche, droite]);
}

function MetricChart({ metric }: { metric: Metric }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const lignes = rows.value;
  const choisie = selectedFrame.value;
  const reference = referenceFrame.value;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const surface = prepare(canvas, HEIGHT);
    if (!surface) return;
    const { ctx, width, height } = surface;
    fillBackground(surface);

    const { min, max } = metricRange(metric);
    const haut = PADDING.top + RADIUS;
    const bas = height - PADDING.bottom - RADIUS;

    const y = (row: Measurement) => {
      const valeur = row[metric];
      return scale(typeof valeur === 'number' ? valeur : min, [min, max], [bas, haut]);
    };

    // The line joining the points in acquisition order: it is what gives the shape of the
    // batch. Without it one would see only a cloud, and a steady drift would pass for
    // dispersion.
    ctx.beginPath();
    lignes.forEach((row, index) => {
      const px = pointX(index, lignes.length, width);
      const py = y(row);
      if (index === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.strokeStyle = token('--vscode-panel-border', '#3c3c3c');
    ctx.lineWidth = 1;
    ctx.stroke();

    const retenue = token('--vscode-charts-green', '#4ec9b0');
    const ecartee = token('--vscode-errorForeground', '#f48771');
    lignes.forEach((row, index) => {
      const px = pointX(index, lignes.length, width);
      const py = y(row);
      ctx.beginPath();
      ctx.arc(px, py, row.frame === choisie ? RADIUS + 2 : RADIUS, 0, Math.PI * 2);
      ctx.fillStyle = row.approved ? retenue : ecartee;
      ctx.fill();
      if (row.frame === choisie) {
        ctx.strokeStyle = token('--vscode-focusBorder', '#007fd4');
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      // The registration reference fixes the geometry of the whole group: a ring, so that one
      // sees at once whether one is about to drop precisely that one.
      if (row.frame === reference) {
        ctx.beginPath();
        ctx.arc(px, py, RADIUS + 3.5, 0, Math.PI * 2);
        ctx.strokeStyle = token('--vscode-charts-yellow', '#dcdcaa');
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    });

    // The bounds spelled out, failing which a nicely spread cloud could just as well span
    // 0.01 pixel of FWHM as three.
    ctx.fillStyle = token('--vscode-descriptionForeground', '#9d9d9d');
    ctx.font = `10px ${token('--retina-font-mono', 'monospace')}`;
    ctx.textAlign = 'left';
    ctx.fillText(max.toPrecision(3), PADDING.left, PADDING.top + 2);
    ctx.textBaseline = 'bottom';
    ctx.fillText(min.toPrecision(3), PADDING.left, height - 1);
    ctx.textBaseline = 'alphabetic';
  }, [lignes, metric, choisie, reference]);

  /** The frame horizontally closest to the click. */
  const frameAt = (event: PointerEvent): Measurement | null => {
    if (!lignes.length) return null;
    const canvas = event.currentTarget as HTMLCanvasElement;
    const width = canvas.clientWidth;
    let meilleure: Measurement | null = null;
    let distance = Infinity;
    lignes.forEach((row, index) => {
      const ecart = Math.abs(pointX(index, lignes.length, width) - event.offsetX);
      if (ecart < distance) {
        distance = ecart;
        meilleure = row;
      }
    });
    return meilleure;
  };

  return (
    <figure style={{ margin: 0, display: 'grid', gap: '2px' }}>
      <figcaption style={{ fontSize: '11px', color: 'var(--vscode-descriptionForeground)' }}>
        {LABEL[metric]}
      </figcaption>
      <canvas
        ref={canvasRef}
        aria-label={m.metric_chart_label({ metric: LABEL[metric] })}
        title={m.metric_chart_hint()}
        style={{ width: '100%', height: `${HEIGHT}px`, cursor: 'pointer', touchAction: 'none' }}
        onPointerDown={(event) => {
          const row = frameAt(event as PointerEvent);
          if (row) selectedFrame.value = row.frame;
        }}
        onDblClick={(event) => {
          const row = frameAt(event as unknown as PointerEvent);
          if (row) openFrame(row.frame);
        }}
      />
    </figure>
  );
}

export function MetricGrid() {
  const lignes = rows.value;
  if (!lignes.length) return null;
  const choisie = lignes.find((r) => r.frame === selectedFrame.value);
  return (
    <div style={{ display: 'grid', gap: '10px' }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '10px',
        }}
      >
        {METRICS.map((metric) => (
          <MetricChart key={metric} metric={metric} />
        ))}
      </div>
      <p style={{ margin: 0, fontSize: '11px', color: 'var(--vscode-descriptionForeground)' }}>
        {choisie
          ? choisie.approved
            ? m.metric_selected({
                name: basename(choisie.frame),
                weight: choisie.weight.toFixed(4),
              })
            : m.metric_selected_rejected({
                name: basename(choisie.frame),
                weight: choisie.weight.toFixed(4),
                reason: choisie.rejected_by ?? m.selector_reject_unknown(),
              })
          : m.metric_hint()}
      </p>
    </div>
  );
}
