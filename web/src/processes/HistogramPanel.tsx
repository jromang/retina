// Custom panel of the processes that deform the tones.
//
// Setting a black point or a curve without seeing the distribution being moved is a blind
// exercise: it is the only case in the catalogue where the form, on its own, hides most of the
// information. The histogram shows the original here as a faded background and the **result**
// on top, with the transfer curve — hence what the setting does, not only what it is worth.
//
// The function plotted is the domain's, ported identically: `mtf` for
// `HistogramTransformation` (the same closed form as the shader), `pchip` for
// `CurvesTransformation` (mirror of `processes/curves.py::_pchip`), `ghsTransfer` for
// `GeneralizedHyperbolicStretch` (mirror of `processes/stretch.py::ghs_transfer`). The plot
// therefore cannot diverge from the computation — and one parity fixture per mirror holds it.

import { activeView } from '../state/store';
import { Histogram, type Transfer, useHistogram } from '../ui/Histogram';
import { applyChannelStf } from '../viewport/shaders';
import { CurveEditor, pchip } from './CurveEditor';
import type { CustomPanelProps } from './customPanels';
import { ghsTransfer } from './ghs';
import { m } from '../paraglide/messages';

type Point = [number, number];

function number(values: Record<string, unknown>, key: string, fallback: number): number {
  const raw = values[key];
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : fallback;
}

/** The transformation being edited, as the domain will apply it. */
function transferFor(processId: string, values: Record<string, unknown>): Transfer {
  if (processId === 'CurvesTransformation') {
    const points: Point[] =
      Array.isArray(values['points']) && values['points'].length >= 2
        ? (values['points'] as Point[]).map((p) => [Number(p[0]), Number(p[1])])
        : [
            [0, 0],
            [1, 1],
          ];
    return (x) => Math.min(Math.max(pchip(points, x), 0), 1);
  }
  if (processId === 'GeneralizedHyperbolicStretch') {
    const p = {
      stretchFactor: number(values, 'stretch_factor', 0),
      localIntensity: number(values, 'local_intensity', 0),
      symmetryPoint: number(values, 'symmetry_point', 0),
      protectShadows: number(values, 'protect_shadows', 0),
      protectHighlights: number(values, 'protect_highlights', 1),
      invert: values['invert'] === true,
    };
    return (x) => ghsTransfer(x, p);
  }
  const shadows = number(values, 'shadows', 0);
  const midtones = number(values, 'midtones', 0.5);
  const highlights = number(values, 'highlights', 1);
  return (x) => applyChannelStf(x, shadows, midtones, highlights);
}

export function HistogramPanel({ processId, values }: CustomPanelProps) {
  const view = activeView.value;
  const data = useHistogram(view?.id, view?.pixel_gen);
  if (!view) {
    return (
      <p style={{ fontSize: '11px', color: 'var(--vscode-descriptionForeground)', margin: 0 }}>
        {m.histogram_no_view()}
      </p>
    );
  }
  return (
    <div style={{ display: 'grid', gap: '4px', marginBottom: '8px' }}>
      <Histogram data={data} transfer={transferFor(processId, values)} />
      <p style={{ margin: 0, fontSize: '11px', color: 'var(--vscode-descriptionForeground)' }}>
        {m.histogram_preview_hint()}
      </p>
    </div>
  );
}

/** Re-export: the curve editor remains the field of the `points` parameter. */
export { CurveEditor };
