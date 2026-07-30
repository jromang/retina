// Light curve — magnitude as a function of time, with error bars.
//
// The domain can measure and export everything without us; this panel adds only one thing,
// but a decisive one: **seeing the shape**. An eclipse, a transit, a cloudy spell or a
// comparison star that drifts are recognised at a glance and read in no sorted column.
//
// Home-made 2D canvas, like `MetricGrid` and for the same reason: a few dozen points and two
// series do not justify bundling a charting library, whose weight would be paid at every
// load.
//
// **The magnitude axis is inverted** — a photometric convention two thousand years old: a
// smaller magnitude is a brighter star, hence higher up. Forgetting it would draw the
// eclipses upside down.

import { useEffect, useRef } from 'preact/hooks';

import { lastFinished } from '../processes/jobs';
import { m } from '../paraglide/messages';
import { fillBackground, prepare, scale, token } from '../ui/canvas';

const HEIGHT = 320;
const PADDING = { left: 56, right: 16, top: 16, bottom: 34 };
const RADIUS = 3;

export interface CurvePoint {
  frame?: string;
  jd: number | null;
  mag: number | null;
  mag_err: number | null;
  check_mag: number | null;
  airmass: number | null;
  filter?: string;
}

export interface CurveResult {
  n_frames: number;
  n_measured: number;
  points: CurvePoint[];
  mode?: string;
  standardized?: boolean;
  output_csv?: string;
  output_aavso?: string;
}

/** Bounds of a series, margin included; `null` if the series is empty. */
function bounds(values: number[]): { min: number; max: number } | null {
  const finis = values.filter((v) => Number.isFinite(v));
  if (!finis.length) return null;
  const min = Math.min(...finis);
  const max = Math.max(...finis);
  // A perfectly flat series has zero span: without this margin, every point would pile up on
  // a single line and the scale would divide by zero.
  const marge = (max - min) * 0.08 || Math.abs(max) * 0.01 || 0.01;
  return { min: min - marge, max: max + marge };
}

function Chart({ points }: { points: CurvePoint[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const surface = prepare(canvas, HEIGHT);
    if (!surface) return;
    const { ctx, width, height } = surface;
    fillBackground(surface);

    const mesures = points.filter((p) => p.jd !== null && p.mag !== null);
    if (!mesures.length) return;

    const jds = mesures.map((p) => p.jd as number);
    // The vertical scale covers both series: otherwise the check star would fall outside the
    // frame, and it is precisely the one we want to be able to compare with the target.
    const magnitudes = mesures.flatMap((p) =>
      [p.mag, p.check_mag].filter((v): v is number => v !== null),
    );
    const bornesX = bounds(jds);
    const bornesY = bounds(magnitudes);
    if (!bornesX || !bornesY) return;

    const gauche = PADDING.left;
    const droite = width - PADDING.right;
    const haut = PADDING.top;
    const bas = height - PADDING.bottom;
    const x = (jd: number) => scale(jd, [bornesX.min, bornesX.max], [gauche, droite]);
    // Axis inversion: the lowest magnitude (the brightest star) at the top.
    const y = (mag: number) => scale(mag, [bornesY.min, bornesY.max], [bas, haut]);

    const grille = token('--vscode-panel-border', '#3c3c3c');
    const texte = token('--vscode-descriptionForeground', '#9d9d9d');
    ctx.strokeStyle = grille;
    ctx.fillStyle = texte;
    ctx.lineWidth = 1;
    ctx.font = '10px var(--vscode-font-family, sans-serif)';

    ctx.beginPath();
    ctx.moveTo(gauche, haut);
    ctx.lineTo(gauche, bas);
    ctx.lineTo(droite, bas);
    ctx.stroke();

    for (let i = 0; i <= 4; i++) {
      const mag = bornesY.min + ((bornesY.max - bornesY.min) * i) / 4;
      const py = y(mag);
      ctx.globalAlpha = 0.25;
      ctx.beginPath();
      ctx.moveTo(gauche, py);
      ctx.lineTo(droite, py);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(mag.toFixed(3), gauche - 6, py);
    }

    // The abscissa is an integer JD plus a fraction: showing the full JD would give seven
    // identical digits across the whole width. We pull the integer out into a caption and
    // graduate the fraction, which is the only thing that varies.
    const jour = Math.floor(bornesX.min);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let i = 0; i <= 4; i++) {
      const jd = bornesX.min + ((bornesX.max - bornesX.min) * i) / 4;
      ctx.fillText((jd - jour).toFixed(4), x(jd), bas + 6);
    }
    ctx.textAlign = 'left';
    ctx.fillText(`JD − ${jour}`, gauche, bas + 20);

    const dessiner = (
      valeurDe: (p: CurvePoint) => number | null,
      couleur: string,
      avecErreur: boolean,
    ) => {
      ctx.strokeStyle = couleur;
      ctx.fillStyle = couleur;
      for (const point of mesures) {
        const valeur = valeurDe(point);
        if (valeur === null || !Number.isFinite(valeur)) continue;
        const px = x(point.jd as number);
        const py = y(valeur);
        if (avecErreur && point.mag_err) {
          ctx.globalAlpha = 0.5;
          ctx.beginPath();
          ctx.moveTo(px, y(valeur - point.mag_err));
          ctx.lineTo(px, y(valeur + point.mag_err));
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
        ctx.beginPath();
        ctx.arc(px, py, RADIUS, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    dessiner((p) => p.check_mag, token('--vscode-charts-orange', '#d18616'), false);
    dessiner((p) => p.mag, token('--vscode-charts-blue', '#4fc1ff'), true);
  }, [points]);

  return (
    <canvas
      ref={canvasRef}
      aria-label={m.panel_lightcurve()}
      style={{ width: '100%', height: `${HEIGHT}px` }}
    />
  );
}

/** Colour dot of the legend — same hue as the series it names. */
function Pastille({ couleur }: { couleur: string }) {
  return (
    <span
      style={{
        display: 'inline-block', width: '10px', height: '10px', borderRadius: '50%',
        background: couleur, marginRight: '4px', verticalAlign: 'middle',
      }}
    />
  );
}

export function LightCurveTab() {
  const job = lastFinished('LightCurve');
  const resultat = (job?.result ?? null) as CurveResult | null;

  if (!resultat || !resultat.points?.length) {
    return (
      <div style={{ padding: '16px', color: 'var(--vscode-descriptionForeground)' }}>
        {m.lightcurve_empty()}
      </div>
    );
  }

  const mesures = resultat.points.filter((p) => p.mag !== null && p.jd !== null);
  const magnitudes = mesures.map((p) => p.mag as number);
  const amplitude = magnitudes.length
    ? Math.max(...magnitudes) - Math.min(...magnitudes)
    : 0;
  const discret = { fontSize: '11px', color: 'var(--vscode-descriptionForeground)' };

  return (
    <div style={{ display: 'grid', gap: '8px', padding: '10px' }}>
      <div style={{ display: 'flex', gap: '16px', ...discret }}>
        <span>{m.lightcurve_measured({ n: mesures.length, total: resultat.n_frames })}</span>
        <span>{m.lightcurve_amplitude({ value: amplitude.toFixed(3) })}</span>
        <span>
          {resultat.standardized ? m.lightcurve_standard() : m.lightcurve_differential()}
        </span>
      </div>
      <Chart points={resultat.points} />
      <div style={{ display: 'flex', gap: '16px', ...discret }}>
        <span>
          <Pastille couleur="var(--vscode-charts-blue, #4fc1ff)" />
          {m.lightcurve_target()}
        </span>
        <span>
          <Pastille couleur="var(--vscode-charts-orange, #d18616)" />
          {m.lightcurve_check()}
        </span>
      </div>
    </div>
  );
}
