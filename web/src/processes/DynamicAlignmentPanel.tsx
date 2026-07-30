// Custom panel of DynamicAlignment — manual registration, point by point.
//
// Each pair is laid down in two clicks: first on the image **to register**, then on the
// corresponding spot of the **reference** image. The first reference click freezes
// `reference`, which fixes the output geometry.
//
// # Why the tool routes by window
//
// The gesture crosses two viewports, and clicking the second changes the *active* window.
// Routing on the active view would therefore put both points on the same side from the second
// click onwards. The tool event carries `windowId` and `viewId` precisely for that (cf.
// `dynamicTool.ts`): the panel decides based on *where* the click landed, not on what is
// active.
//
// The interaction mode is set on **every** open window: a mode per window means that arming
// only the active window would leave the other in readout, where the click does nothing.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { plural } from '../ui/plural';
import { client } from '../api/client';
import { activeView, windows } from '../state/store';
import { armDynamicTool } from '../viewport/dynamicTool';
import {
  addPoint,
  expecting,
  pairs,
  pendingSource,
  readyToApply,
  removeLast,
  toOverlays,
} from './alignPairs';
import type { CustomPanelProps } from './customPanels';
import { jobFor, runProcess } from './jobs';

const TAG_SOURCE = 'dynalign.source';
const TAG_TARGET = 'dynalign.target';
const SOURCE_COLOR = [1, 0.75, 0.2, 0.95];
const TARGET_COLOR = [0.35, 0.85, 1, 0.95];

function listOf(values: Record<string, unknown>, key: string): number[] {
  const brut = values[key];
  return Array.isArray(brut) ? (brut as number[]).map(Number) : [];
}

export function DynamicAlignmentTool({ values, onChange }: CustomPanelProps) {
  const view = activeView.value;
  const ouvertes = windows.value;
  // Disarmed on opening, like the DBE panel. A panel left open and no longer being watched
  // must not seize the pointer: several tools open at the same time would fight over the
  // clicks, and the last one armed would win without anything saying so. A registration test
  // did in fact see its clicks land in a clone stamp that had been left open.
  const [placing, setPlacing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const job = jobFor('DynamicAlignment');

  const source = listOf(values, 'source');
  const target = listOf(values, 'target');
  const reference = typeof values['reference'] === 'string' ? (values['reference'] as string) : '';
  const attendu = expecting(source, target);
  const liste = pairs(source, target);

  // The view to register: the one that was active when we started. Memorised, otherwise
  // clicking the reference image would make it the source at the next click.
  const sourceViewId = useRef<string | null>(null);
  if (sourceViewId.current === null && view) sourceViewId.current = view.id;

  const latest = useRef({ values, onChange, source, target, reference, sourceView: sourceViewId });
  latest.current = { values, onChange, source, target, reference, sourceView: sourceViewId };

  useEffect(() => {
    if (!placing) return;
    // Every window, not only the active one — the mode is a *per-window* state.
    for (const win of ouvertes) {
      void client
        .call('app.set_interaction_mode', { mode: 'dynamic', window: win.id })
        .catch(() => undefined);
    }
    const disarm = armDynamicTool({
      id: 'dynamicalignment.pairs',
      label: m.align_tool_label(),
      cursor: 'crosshair',
      onDown: ({ point, viewId }) => {
        const s = latest.current;
        const attend = expecting(s.source, s.target);
        const origine = s.sourceView.current;
        // Guard: a source point must come from the view being registered, a target point
        // from another one. Without it, two clicks in the same place would form an identity
        // pair — a registration that registers nothing, and nothing to say so.
        if (attend === 'source' && origine && viewId !== origine) return;
        if (attend === 'target' && origine && viewId === origine) return;

        const next = addPoint(s.source, s.target, point);
        const patch: Record<string, unknown> = { ...s.values, ...next };
        // The output geometry is that of the view where the reference is pointed at.
        if (attend === 'target' && !s.reference) patch['reference'] = viewId;
        s.onChange(patch);
      },
    });
    return () => {
      disarm();
      for (const win of ouvertes) {
        void client
          .call('app.set_interaction_mode', { mode: 'readout', window: win.id })
          .catch(() => undefined);
      }
    };
  }, [placing, ouvertes.length]);

  // The points are laid down in the window where they were clicked: sources in the one being
  // registered, targets in the reference. Two distinct tags, hence two independent sets.
  useEffect(() => {
    const origine = sourceViewId.current;
    const fenetreDe = (viewId: string | null) =>
      ouvertes.find((win) => win.views.some((v) => v.id === viewId))?.id;

    const fenetreSource = fenetreDe(origine);
    if (fenetreSource) {
      void client
        .call('app.set_overlays', {
          tag: TAG_SOURCE,
          window: fenetreSource,
          overlays: toOverlays(source, SOURCE_COLOR),
        })
        .catch(() => undefined);
    }
    const fenetreCible = fenetreDe(reference || null);
    if (fenetreCible) {
      void client
        .call('app.set_overlays', {
          tag: TAG_TARGET,
          window: fenetreCible,
          overlays: toOverlays(target, TARGET_COLOR),
        })
        .catch(() => undefined);
    }
  }, [source.length, target.length, reference, ouvertes.length]);

  useEffect(
    () => () => {
      for (const tag of [TAG_SOURCE, TAG_TARGET]) {
        for (const win of windows.value) {
          void client
            .call('app.set_overlays', { tag, window: win.id, overlays: [] })
            .catch(() => undefined);
        }
      }
    },
    [],
  );

  const pending = pendingSource(source, target);

  return (
    <div style={{ display: 'grid', gap: '6px', marginBottom: '8px' }}>
      <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', gap: '4px', alignItems: 'center', fontSize: '12px' }}>
          <input
            type="checkbox"
            checked={placing}
            onChange={(e) => setPlacing((e.target as HTMLInputElement).checked)}
          />
          {m.align_place_pairs()}
        </label>
        <button
          class="btn"
          disabled={source.length === 0}
          onClick={() => onChange({ ...values, ...removeLast(source, target) })}
        >
          {m.align_undo_last()}
        </button>
        <button
          class="btn"
          disabled={source.length === 0 && target.length === 0}
          onClick={() => onChange({ ...values, source: [], target: [], reference: '' })}
        >
          {m.align_clear_all()}
        </button>
        <button
          class="btn"
          title={m.align_link_tip()}
          onClick={() => void client.call('app.link_viewports').catch(() => undefined)}
        >
          {m.align_link()}
        </button>
        {/* A button specific to the panel, and not the form's: the latter applies to the
            *active* view, yet laying down the last reference point makes the reference
            active. We would therefore register the image serving as the model. Here the
            target is explicit. */}
        <button
          class="btn btn-primary"
          disabled={!readyToApply(source, target) || job !== null || !sourceViewId.current}
          title={m.align_apply_tip({ view: sourceViewId.current ?? '' })}
          onClick={() => {
            const cible = sourceViewId.current;
            if (!cible) return;
            setError(null);
            runProcess('DynamicAlignment', values, cible).catch((e: unknown) =>
              setError(e instanceof Error ? e.message : String(e)),
            );
          }}
        >
          {m.align_apply({ view: sourceViewId.current ?? '' })}
        </button>
      </div>

      {error && (
        <p style={{ margin: 0, fontSize: '11px', color: 'var(--vscode-errorForeground)' }}>{error}</p>
      )}

      <p
        style={{
          margin: 0,
          fontSize: '11px',
          color: 'var(--vscode-descriptionForeground)',
          lineHeight: 1.4,
        }}
      >
        {attendu === 'source'
          ? m.align_click_source({
              view: sourceViewId.current ?? m.align_image_to_register(),
            })
          : m.align_point_placed({
              n: liste.length + 1,
              x: pending?.[0].toFixed(0) ?? '',
              y: pending?.[1].toFixed(0) ?? '',
            })}
        {' '}
        {plural(
          liste.length,
          m.align_pair_one({ count: liste.length }),
          m.align_pair_many({ count: liste.length }),
        )}
        {reference && ` · ${m.align_reference({ view: reference })}`}
      </p>

      {!readyToApply(source, target) && liste.length > 0 && (
        <p style={{ margin: 0, fontSize: '11px', color: 'var(--vscode-charts-yellow)' }}>
          {m.align_min_pairs()}
        </p>
      )}

      {liste.length > 0 && (
        <ul style={{ margin: 0, padding: 0, listStyle: 'none', fontSize: '11px' }}>
          {liste.map((pair, index) => (
            <li key={index} style={{ fontFamily: 'var(--retina-font-mono)' }}>
              {index + 1}. ({pair.sx.toFixed(1)}, {pair.sy.toFixed(1)}) → ({pair.tx.toFixed(1)},{' '}
              {pair.ty.toFixed(1)})
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
