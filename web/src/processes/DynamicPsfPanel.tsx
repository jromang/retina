// Custom panel of DynamicPSF — measuring the shape of stars, and seeing it.
//
// Two gestures: "Detect" fits the brightest stars in the field, or one clicks the interesting
// ones oneself. The second goes through the process's `positions` parameter: the gesture is
// therefore scriptable identically (`DynamicPSF(positions=[x, y]).execute_on(view)`), and the
// interface has no capability of its own.
//
// The result arrives through the `job.done` notification, not through the snapshot — the
// latter only lists the jobs *in flight*. A reconnection therefore loses the table; we
// memorise it on the panel side and relaunch the measurement if need be. That is accepted:
// recomputing costs a second, and making measurements travel in the application state would be
// paying for persistence for the sake of a display.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { plural } from '../ui/plural';
import { client } from '../api/client';
import { activeView } from '../state/store';
import { armDynamicTool } from '../viewport/dynamicTool';
import type { CustomPanelProps } from './customPanels';
import { jobFor, lastFinished, runProcess } from './jobs';

const TAG = 'dynamicpsf';

interface Star {
  x: number;
  y: number;
  fwhm: number;
  fwhm_x: number;
  fwhm_y: number;
  eccentricity: number;
  flux: number;
  theta: number;
  beta?: number;
}

type SortKey = 'fwhm' | 'eccentricity' | 'flux';

/** Key of the view property where the measurements live — it is a domain identifier. */
const PSF_KEY = 'psf';

function starsOf(result: Record<string, unknown> | null | undefined): Star[] {
  const brut = result?.['stars'];
  return Array.isArray(brut) ? (brut as Star[]) : [];
}

export function DynamicPsfTool({ values, onChange }: CustomPanelProps) {
  const view = activeView.value;
  const [stars, setStars] = useState<Star[]>([]);
  const [sort, setSort] = useState<SortKey>('flux');
  const [picking, setPicking] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const job = jobFor('DynamicPSF');
  const fini = lastFinished('DynamicPSF');
  const latest = useRef({ values, onChange });
  latest.current = { values, onChange };

  // The job's result is picked up as soon as it arrives, then **pushed into the view**: the
  // job is forgotten one second after it ends, and a measurement that cost a star detection
  // must not die with it. Since then it follows the view, enters the `.retina` project, and
  // survives a reconnection — which was not the case when it lived only in the `job.done`
  // notification.
  useEffect(() => {
    if (!fini?.result || !view) return;
    const mesurees = starsOf(fini.result);
    setStars(mesurees);
    setNote(mesurees.length === 0 ? m.psf_no_star() : null);
    void client
      .call('app.set_view_property', { view: view.id, key: PSF_KEY, value: fini.result })
      .catch(() => undefined);
  }, [fini?.id, fini?.result]);

  // Read back: when the panel mounts, when the view changes, and when the view's write counter
  // moves (a measurement launched from the console, or a reopened project). The snapshot
  // carries only a summary — the stars are asked for, they are not broadcast.
  const rev = view?.properties?.rev ?? null;
  useEffect(() => {
    if (!view) {
      setStars([]);
      return;
    }
    let annule = false;
    void client
      .call<Record<string, unknown> | null>('app.view_property', {
        view: view.id,
        key: PSF_KEY,
      })
      .then((mesure) => {
        if (annule) return;
        setStars(starsOf(mesure));
      })
      .catch(() => undefined);
    return () => {
      annule = true;
    };
  }, [view?.id, rev]);

  useEffect(() => {
    if (!picking || !view) return;
    void client.call('app.set_interaction_mode', { mode: 'dynamic' }).catch(() => undefined);
    const disarm = armDynamicTool({
      id: 'dynamicpsf.pick',
      label: m.psf_tool_label(),
      cursor: 'crosshair',
      onDown: ({ point }) => {
        const s = latest.current;
        const positions = Array.isArray(s.values['positions'])
          ? (s.values['positions'] as number[])
          : [];
        // We stack into the parameter, and relaunch the measurement: it is the process that
        // fits, the panel only points at where to look.
        const suivantes = [...positions, Math.round(point[0]), Math.round(point[1])];
        s.onChange({ ...s.values, positions: suivantes });
        runProcess('DynamicPSF', { ...s.values, positions: suivantes }, view.id).catch(
          (e: unknown) => setNote(e instanceof Error ? e.message : String(e)),
        );
      },
    });
    return () => {
      disarm();
      void client.call('app.set_interaction_mode', { mode: 'readout' }).catch(() => undefined);
    };
  }, [picking, view?.id]);

  // The fitted ellipses, as a domain overlay: the same line works from the console, and it is
  // what makes it possible to *see* that a star is elongated instead of reading a number.
  useEffect(() => {
    if (!view) return;
    void client
      .call('app.set_overlays', {
        tag: TAG,
        overlays:
          stars.length === 0
            ? []
            : [
                {
                  kind: 'ellipses',
                  // Radii = half-FWHM: the ellipse drawn is the full width at half maximum,
                  // the quantity the FWHM column announces. An arbitrary radius would make
                  // the drawing pretty and not comparable to the table.
                  items: stars.map((star) => ({
                    x: star.x,
                    y: star.y,
                    rx: star.fwhm_x / 2,
                    ry: star.fwhm_y / 2,
                    theta: star.theta,
                  })),
                  color: [0.4, 1, 0.5, 0.9],
                  width: 1.2,
                },
              ],
      })
      .catch(() => undefined);
  }, [stars, view?.id]);

  useEffect(
    () => () => {
      void client.call('app.set_overlays', { tag: TAG, overlays: [] }).catch(() => undefined);
    },
    [],
  );

  const detect = () => {
    if (!view) return;
    setNote(null);
    // `positions` emptied: the process goes back through automatic detection.
    onChange({ ...values, positions: [] });
    runProcess('DynamicPSF', { ...values, positions: [] }, view.id).catch((e: unknown) =>
      setNote(e instanceof Error ? e.message : String(e)),
    );
  };

  const clear = () => {
    setStars([]);
    setNote(null);
    onChange({ ...values, positions: [] });
  };

  const triees = [...stars].sort((a, b) =>
    sort === 'flux' ? b.flux - a.flux : a[sort] - b[sort],
  );

  return (
    <div style={{ display: 'grid', gap: '6px', marginBottom: '8px' }}>
      <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
        <button class="btn btn-primary" disabled={job !== null || !view} onClick={detect}>
          {m.psf_detect()}
        </button>
        <label style={{ display: 'flex', gap: '4px', alignItems: 'center', fontSize: '12px' }}>
          <input
            type="checkbox"
            checked={picking}
            onChange={(e) => setPicking((e.target as HTMLInputElement).checked)}
          />
          {m.psf_click_stars()}
        </label>
        <button class="btn" disabled={stars.length === 0} onClick={clear}>
          {m.psf_clear()}
        </button>
        <span
          style={{ marginLeft: 'auto', fontSize: '11px', color: 'var(--vscode-descriptionForeground)' }}
        >
          {plural(
            stars.length,
            m.psf_star_one({ count: stars.length }),
            m.psf_star_many({ count: stars.length }),
          )}
        </span>
      </div>

      {note && (
        <p style={{ margin: 0, fontSize: '11px', color: 'var(--vscode-descriptionForeground)' }}>
          {note}
        </p>
      )}

      {stars.length > 0 && (
        <div style={{ maxHeight: '190px', overflowY: 'auto' }}>
          <table class="data-table" style={{ width: '100%', fontSize: '11px' }}>
            <thead>
              <tr>
                <th scope="col">x</th>
                <th scope="col">y</th>
                {(['fwhm', 'eccentricity', 'flux'] as SortKey[]).map((key) => (
                  <th
                    key={key}
                    scope="col"
                    aria-sort={sort === key ? 'ascending' : 'none'}
                    onClick={() => setSort(key)}
                    style={{ cursor: 'pointer' }}
                    title={m.psf_sort_tip()}
                  >
                    {key === 'fwhm' ? 'FWHM' : key === 'eccentricity' ? m.psf_col_ecc() : 'flux'}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {triees.map((star) => (
                <tr
                  key={`${star.x.toFixed(2)},${star.y.toFixed(2)}`}
                  tabIndex={0}
                  title={m.psf_center_tip()}
                  onClick={() =>
                    void client
                      .call('app.set_viewport', { center: [star.x, star.y] })
                      .catch(() => undefined)
                  }
                  onKeyDown={(event: KeyboardEvent) => {
                    if (event.key !== 'Enter') return;
                    void client
                      .call('app.set_viewport', { center: [star.x, star.y] })
                      .catch(() => undefined);
                  }}
                >
                  <td>{star.x.toFixed(1)}</td>
                  <td>{star.y.toFixed(1)}</td>
                  <td>{star.fwhm.toFixed(2)}</td>
                  <td>{star.eccentricity.toFixed(3)}</td>
                  <td>{star.flux.toExponential(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p
        style={{
          margin: 0,
          fontSize: '11px',
          color: 'var(--vscode-descriptionForeground)',
          lineHeight: 1.4,
        }}
      >
        {m.psf_hint_a()} <strong>{m.psf_hint_fwhm()}</strong> {m.psf_hint_b()}
      </p>
    </div>
  );
}
