// Custom CloneStamp panel — the clone stamp driven by the pointer.
//
// A click arms the source; then one **paints by dragging**, and the whole stroke leaves as a
// single instance (`points`, cf. `cloneOps.ts`). Pressing and releasing without moving remains
// the two-click gesture of before: the single disc is the case of a one-point stroke, not a
// separate branch. The operations stack up and leave in **one** `process.run_container`: one
// job, one echo, a guaranteed order. Each stroke keeps its history entry, hence undoes
// separately — which is what one wants of a retouch.
//
// The form's standard "Apply" button remains usable: it applies the operation described by the
// fields, on its own. This panel adds the gesture and the stacking, it does not replace them —
// a clone stamp typed in the console stays possible and identical.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { plural } from '../ui/plural';
import { client } from '../api/client';
import { activeView } from '../state/store';
import { armDynamicTool } from '../viewport/dynamicTool';
import {
  EMPTY_CLONE_STATE,
  beginStroke,
  disarm,
  endStroke,
  extendStroke,
  popOp,
  removeOp,
  toContainer,
  toOverlays,
  type CloneState,
} from './cloneOps';
import type { CustomPanelProps } from './customPanels';
import { jobFor, runContainer } from './jobs';

const TAG = 'clonestamp';

// `onChange` is not used: radius and softness are set in the auto-generated fields, and the
// panel only *reads* them, to draw and to build its operations.
export function CloneStampTool({ values }: CustomPanelProps) {
  const view = activeView.value;
  const [state, setState] = useState<CloneState>(EMPTY_CLONE_STATE);
  // Disarmed on opening, like the DBE panel. A panel left open and no longer being watched
  // must not seize the pointer: several tools open at the same time would fight over the
  // clicks, and the last one armed would win without anything saying so. A registration test
  // did in fact see its clicks land in a clone stamp that had been left open.
  const [placing, setPlacing] = useState(false);
  const [cursor, setCursor] = useState<readonly [number, number] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const radius = typeof values['radius'] === 'number' ? (values['radius'] as number) : 8;
  const softness = typeof values['softness'] === 'number' ? (values['softness'] as number) : 0.3;
  const job = jobFor('CloneStamp ×N');

  const latest = useRef({ state, radius, softness, cursor });
  latest.current = { state, radius, softness, cursor };

  useEffect(() => {
    if (!placing || !view) return;
    void client.call('app.set_interaction_mode', { mode: 'dynamic' }).catch(() => undefined);
    const disarmTool = armDynamicTool({
      id: 'clonestamp.ops',
      label: m.clone_tool_label(),
      cursor: 'crosshair',
      onDown: ({ point, event }) => {
        const s = latest.current;
        // Alt (or a right-click elsewhere in the app) disarms: with no way out, a source
        // placed by mistake would force one to drop an unwanted operation.
        if (event.altKey) {
          setState((prev) => disarm(prev));
          return;
        }
        setState((prev) => beginStroke(prev, point, s.radius, s.softness));
      },
      // **Functional** updates: a fast drag sends several `pointermove` between two renders,
      // and reading the state through the ref would lose the intermediate points — hence gaps
      // in the stroke, all the more visible the faster the hand moves.
      onMove: ({ point }) => {
        setCursor(point);
        setState((prev) => extendStroke(prev, point));
      },
      onUp: () => setState((prev) => endStroke(prev)),
      chrome: (ctx, camera) => {
        const s = latest.current;
        const rayon = camera.imageScalarToViewport(s.radius);
        const stroke = s.state.stroke;
        ctx.save();
        if (s.cursor) {
          const [cx, cy] = camera.imageToViewport(s.cursor);
          // The disc shows what the stamp will cover: without it, `radius` is a number in a
          // field, and the size is discovered after the fact.
          ctx.strokeStyle = 'rgba(255, 153, 51, 0.9)';
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(cx, cy, Math.max(rayon, 2), 0, Math.PI * 2);
          ctx.stroke();

          if (stroke) {
            // **Ghost** cursor of the source: during the stroke the offset is constant, so
            // the zone being read moves with the hand. Showing it avoids discovering after
            // the fact that a star was being copied — the feedback the single click lacked
            // most.
            const [gx, gy] = camera.imageToViewport([
              s.cursor[0] + stroke.srcX - (stroke.points[0] as number),
              s.cursor[1] + stroke.srcY - (stroke.points[1] as number),
            ]);
            ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.arc(gx, gy, Math.max(rayon, 2), 0, Math.PI * 2);
            ctx.stroke();
            ctx.setLineDash([]);
          } else if (s.state.armed) {
            const [ax, ay] = camera.imageToViewport(s.state.armed);
            ctx.setLineDash([4, 3]);
            ctx.beginPath();
            ctx.moveTo(ax, ay);
            ctx.lineTo(cx, cy);
            ctx.stroke();
            ctx.setLineDash([]);
          }
        }
        if (stroke && stroke.points.length >= 4) {
          // The stroke in progress is not an operation yet: it therefore cannot go through
          // the domain overlays, which only carry what is committed. Hence this local draw.
          ctx.strokeStyle = 'rgba(255, 153, 51, 0.65)';
          ctx.lineWidth = Math.max(2 * rayon, 2);
          ctx.lineJoin = 'round';
          ctx.lineCap = 'round';
          ctx.beginPath();
          for (let i = 0; i + 1 < stroke.points.length; i += 2) {
            const [px, py] = camera.imageToViewport([
              stroke.points[i] as number,
              stroke.points[i + 1] as number,
            ]);
            if (i === 0) ctx.moveTo(px, py);
            else ctx.lineTo(px, py);
          }
          ctx.stroke();
        }
        if (s.state.armed) {
          const [ax, ay] = camera.imageToViewport(s.state.armed);
          ctx.strokeStyle = 'rgba(255, 153, 51, 0.95)';
          ctx.beginPath();
          ctx.arc(ax, ay, Math.max(rayon, 2), 0, Math.PI * 2);
          ctx.moveTo(ax - 6, ay);
          ctx.lineTo(ax + 6, ay);
          ctx.moveTo(ax, ay - 6);
          ctx.lineTo(ax, ay + 6);
          ctx.stroke();
        }
        ctx.restore();
      },
    });
    return () => {
      disarmTool();
      void client.call('app.set_interaction_mode', { mode: 'readout' }).catch(() => undefined);
    };
  }, [placing, view?.id]);

  // The committed operations also live in the domain: a script can read them back, and they
  // stay visible if the panel is closed before applying.
  useEffect(() => {
    if (!view) return;
    void client
      .call('app.set_overlays', { tag: TAG, overlays: toOverlays(state.ops) })
      .catch(() => undefined);
  }, [state.ops, view?.id]);

  useEffect(
    () => () => {
      void client.call('app.set_overlays', { tag: TAG, overlays: [] }).catch(() => undefined);
    },
    [],
  );

  const apply = () => {
    if (state.ops.length === 0 || !view) return;
    setError(null);
    runContainer(toContainer(state.ops), view.id, 'CloneStamp ×N')
      // The operations are only cleared once the job is accepted: erasing them at send time
      // would lose the work if the container failed.
      .then(() => setState(EMPTY_CLONE_STATE))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  };

  return (
    <div style={{ display: 'grid', gap: '6px', marginBottom: '8px' }}>
      <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', gap: '4px', alignItems: 'center', fontSize: '12px' }}>
          <input
            type="checkbox"
            checked={placing}
            onChange={(e) => setPlacing((e.target as HTMLInputElement).checked)}
          />
          {m.clone_stamp_on_image()}
        </label>
        <button class="btn" disabled={state.ops.length === 0} onClick={() => setState(popOp(state))}>
          {m.clone_remove_last()}
        </button>
        <button
          class="btn btn-primary"
          disabled={state.ops.length === 0 || job !== null}
          onClick={apply}
          title={m.clone_apply_tip()}
        >
          {plural(
            state.ops.length,
            m.clone_apply_one({ count: state.ops.length }),
            m.clone_apply_many({ count: state.ops.length }),
          )}
        </button>
      </div>

      <p
        style={{
          margin: 0,
          fontSize: '11px',
          color: 'var(--vscode-descriptionForeground)',
          lineHeight: 1.4,
        }}
      >
        {state.armed ? m.clone_source_placed() : m.clone_hint()}
      </p>

      {state.ops.length > 0 && (
        <ul style={{ margin: 0, padding: 0, listStyle: 'none', fontSize: '11px' }}>
          {state.ops.map((op, index) => (
            <li
              key={`${index}:${op.srcX},${op.srcY}->${op.dstX},${op.dstY}`}
              style={{ display: 'flex', gap: '6px', alignItems: 'center', padding: '1px 0' }}
            >
              <span style={{ color: 'var(--vscode-descriptionForeground)' }}>{index + 1}.</span>
              <span style={{ fontFamily: 'var(--retina-font-mono)' }}>
                ({op.srcX}, {op.srcY}) → ({op.dstX}, {op.dstY}) r{op.radius}
              </span>
              {op.points.length > 0 && (
                <span style={{ color: 'var(--vscode-descriptionForeground)' }}>
                  {m.clone_stroke_points({ count: op.points.length / 2 })}
                </span>
              )}
              <button
                class="btn"
                style={{ marginLeft: 'auto', padding: '0 6px' }}
                title={m.clone_remove_op()}
                onClick={() => setState(removeOp(state, index))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p style={{ margin: 0, fontSize: '11px', color: 'var(--vscode-errorForeground)' }}>{error}</p>
      )}
    </div>
  );
}
