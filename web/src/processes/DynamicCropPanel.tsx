// Custom panel of DynamicCrop — cropping with the mouse.
//
// The auto-generated form already exposes x0/y0/x1/y1 and the angle; this panel only adds the
// gesture, and **writes into the same values**. A crop typed in the console
// (`DynamicCrop(x0=0.1, x1=0.9).execute_on(view)`) and a crop drawn with the mouse are
// therefore literally the same process instance — which is the only way to hold parity
// without reimplementing the cutting twice.
//
// The drawing of the handles stays **on the client side** (`DynamicTool.chrome`): it changes
// on every mouse movement. Only the *committed* rectangle goes up to the domain as an overlay,
// where the console can see it.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import { activeView, activeWindow } from '../state/store';
import {
  applyDrag,
  cropSize,
  cursorFor,
  frameAngle,
  handlePositions,
  hitTest,
  isFullFrame,
  normalise,
  rectCorners,
  rectPx,
  type CropMode,
  type CropValues,
  type Handle,
} from '../viewport/cropTool';
import { armDynamicTool, dynamicTool } from '../viewport/dynamicTool';
import type { CustomPanelProps } from './customPanels';

const TAG = 'dyncrop';
/** Grab tolerance, in screen pixels: converted into image pixels through the zoom. */
const GRAB_PX = 7;

function valuesOf(values: Record<string, unknown>): CropValues {
  const num = (key: string, fallback: number) =>
    typeof values[key] === 'number' ? (values[key] as number) : fallback;
  // `mode` is the process enum: anything that is not `rotated_rect` (including its absence, in
  // an icon saved before this parameter existed) means the historical default.
  const mode: CropMode = values['mode'] === 'rotated_rect' ? 'rotated_rect' : 'after_crop';
  return normalise({
    x0: num('x0', 0), y0: num('y0', 0),
    x1: num('x1', 1), y1: num('y1', 1),
    angle: num('angle', 0),
    mode,
  });
}

export function DynamicCropTool({ values, onChange }: CustomPanelProps) {
  const view = activeView.value;
  const win = activeWindow.value;
  // Disarmed on opening, like the DBE panel. A panel left open and no longer being watched
  // must not seize the pointer: several tools open at the same time would fight over the
  // clicks, and the last one armed would win without anything saying so. A registration test
  // did in fact see its clicks land in a clone stamp that had been left open.
  const [active, setActive] = useState(false);
  const [hover, setHover] = useState<Handle | null>(null);

  const crop = valuesOf(values);
  const width = view?.width ?? 0;
  const height = view?.height ?? 0;

  // The gesture in progress lives in a ref: it changes at 60 Hz and must not cause a render.
  // `start` memorises the state at the **beginning** of the drag, so that each movement
  // recomputes from the origin rather than accumulating deltas.
  const drag = useRef<{ handle: Handle; from: readonly [number, number]; start: CropValues } | null>(
    null,
  );
  const latest = useRef({ crop, values, onChange, width, height, active });
  latest.current = { crop, values, onChange, width, height, active };

  useEffect(() => {
    if (!active || !view) return;
    void client.call('app.set_interaction_mode', { mode: 'dynamic' }).catch(() => undefined);

    const disarm = armDynamicTool({
      id: 'dynamiccrop.rect',
      label: m.crop_tool_label(),
      cursor: 'crosshair',
      onDown: ({ point }) => {
        const s = latest.current;
        const handle = hitTest(s.crop, point, s.width, s.height, GRAB_PX / zoom());
        if (!handle) return;
        drag.current = { handle, from: point, start: s.crop };
      },
      onMove: ({ point }) => {
        const s = latest.current;
        const current = drag.current;
        if (!current) {
          const handle = hitTest(s.crop, point, s.width, s.height, GRAB_PX / zoom());
          setHover(handle);
          // The cursor is the only affordance that says "this handle can be grabbed": it is
          // written into the tool, which the viewport reads back. Compared before writing,
          // otherwise every mouse movement would notify the signal for nothing.
          const cursor = cursorFor(handle);
          const tool = dynamicTool.value;
          if (tool && tool.id === 'dynamiccrop.rect' && tool.cursor !== cursor) {
            dynamicTool.value = { ...tool, cursor };
          }
          return;
        }
        // During the drag the form is written to on every movement: this is client state, no
        // server round trip. The process itself only leaves on "Apply".
        s.onChange({
          ...s.values,
          ...applyDrag(current.handle, current.start, current.from, point, s.width, s.height),
        });
      },
      onUp: () => {
        drag.current = null;
      },
      chrome: (ctx, camera) => {
        const s = latest.current;
        if (s.width <= 0 || s.height <= 0) return;
        const rect = rectPx(s.crop, s.width, s.height);
        const tilt = frameAngle(s.crop);
        const coins = rectCorners(s.crop, s.width, s.height);
        const ecran = coins.map((p) => camera.imageToViewport(p));
        const [ancreX, ancreY] = camera.imageToViewport(coins[0]);

        // Darkened outside: showing what is being lost speaks louder than a border, above all
        // when the frame covers almost everything. The hole is the **polygon** of the four
        // corners: tilted, it can no longer be described by a `ctx.rect`.
        ctx.save();
        ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
        ctx.beginPath();
        ctx.rect(0, 0, ctx.canvas.clientWidth, ctx.canvas.clientHeight);
        ecran.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
        ctx.closePath();
        ctx.fill('evenodd');
        ctx.restore();

        // The rest of the chrome is drawn in the **frame's** coordinate system: the camera
        // being only a scaling (cf. camera.ts), the image angle carries over unchanged.
        const [ccx, ccy] = camera.imageToViewport([
          (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2,
        ]);
        const hw = camera.imageScalarToViewport((rect[2] - rect[0]) / 2);
        const hh = camera.imageScalarToViewport((rect[3] - rect[1]) / 2);
        ctx.save();
        ctx.translate(ccx, ccy);
        ctx.rotate((tilt * Math.PI) / 180);

        ctx.strokeStyle = 'rgba(255, 212, 121, 0.95)';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(-hw, -hh, hw * 2, hh * 2);

        // Thirds: the composition guide that every cropping tool offers.
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.22)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 1; i < 3; i += 1) {
          const x = -hw + (hw * 2 * i) / 3;
          const y = -hh + (hh * 2 * i) / 3;
          ctx.moveTo(x, -hh); ctx.lineTo(x, hh);
          ctx.moveTo(-hw, y); ctx.lineTo(hw, y);
        }
        ctx.stroke();

        // Handles: **unrotated** positions (the canvas coordinate system takes care of that),
        // converted into screen offsets from the centre.
        const positions = handlePositions(rect);
        for (const [name, [hx, hy]] of Object.entries(positions)) {
          const px = camera.imageScalarToViewport(hx - (rect[0] + rect[2]) / 2);
          const py = camera.imageScalarToViewport(hy - (rect[1] + rect[3]) / 2);
          const size = name === 'rotate' ? 4 : 3.5;
          if (name === 'rotate') {
            // The arm carries the angle. In `after_crop` it announces a rotation that will
            // come *after* the cut, with an untilted frame; in `rotated_rect` it tilts the
            // frame itself, and therefore follows the pointer.
            ctx.strokeStyle = 'rgba(255, 212, 121, 0.7)';
            ctx.beginPath();
            ctx.moveTo(0, -hh);
            ctx.lineTo(px, py);
            ctx.stroke();
          }
          ctx.fillStyle = name === hover ? '#ffffff' : 'rgba(255, 212, 121, 0.95)';
          ctx.beginPath();
          ctx.arc(px, py, size, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();

        if (s.crop.angle !== 0) {
          // The label stays **upright**: an angle read sideways is an angle read twice.
          // Anchored to the frame's first corner, tilted or not.
          ctx.save();
          ctx.fillStyle = 'rgba(255, 212, 121, 0.95)';
          ctx.font = '11px var(--retina-font-mono)';
          const libelle =
            s.crop.mode === 'rotated_rect'
              ? m.crop_angle_frame({ angle: s.crop.angle.toFixed(1) })
              : m.crop_angle_after({ angle: s.crop.angle.toFixed(1) });
          ctx.fillText(libelle, ancreX + 4, ancreY - 6);
          ctx.restore();
        }
      },
    });

    return () => {
      disarm();
      void client.call('app.set_interaction_mode', { mode: 'readout' }).catch(() => undefined);
    };
  }, [active, view?.id]);

  // The committed rectangle leaves as a domain overlay: visible from the console, and it
  // survives the panel being closed for as long as one takes to decide.
  useEffect(() => {
    if (!view) return;
    const rect = rectPx(crop, width, height);
    void client
      .call('app.set_overlays', {
        tag: TAG,
        // `angle` is only sent if the mode tilts the rectangle: the domain overlay knows how
        // to draw a rotated rect, and that is what the console must see of the region read.
        overlays: isFullFrame(crop)
          ? []
          : [{
              kind: 'rects', rects: [rect], color: [1, 0.83, 0.47, 0.9], width: 1.5,
              angle: frameAngle(crop),
            }],
      })
      .catch(() => undefined);
  }, [crop.x0, crop.y0, crop.x1, crop.y1, crop.angle, crop.mode, view?.id]);

  useEffect(
    () => () => {
      void client.call('app.set_overlays', { tag: TAG, overlays: [] }).catch(() => undefined);
    },
    [],
  );

  const [cw, ch] = cropSize(crop, width, height);

  return (
    <div style={{ display: 'grid', gap: '6px', marginBottom: '8px' }}>
      <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', gap: '4px', alignItems: 'center', fontSize: '12px' }}>
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => setActive((e.target as HTMLInputElement).checked)}
          />
          {m.crop_adjust_on_image()}
        </label>
        <button
          class="btn"
          disabled={isFullFrame(crop) && crop.angle === 0}
          onClick={() => onChange({ ...values, x0: 0, y0: 0, x1: 1, y1: 1, angle: 0 })}
        >
          {m.crop_full_frame()}
        </button>
        <span
          style={{ marginLeft: 'auto', fontSize: '11px', color: 'var(--vscode-descriptionForeground)' }}
        >
          {cw} × {ch} px
        </span>
      </div>
      <p
        style={{
          margin: 0,
          fontSize: '11px',
          color: 'var(--vscode-descriptionForeground)',
          lineHeight: 1.4,
        }}
      >
        {crop.mode === 'rotated_rect' ? (
          m.crop_hint_rotated_rect()
        ) : (
          <>
            {m.crop_hint_a()} <strong>{m.crop_hint_after()}</strong> {m.crop_hint_b()}
          </>
        )}{' '}
        {hover ? m.crop_handle({ handle: hover }) : ''}
      </p>
    </div>
  );

  function zoom(): number {
    // The zoom serves to convert the grab tolerance from screen to image. It comes from the
    // snapshot, not from the renderer: the panel has no access to the camera, and being one
    // frame off during a pan has no consequence on a seven-pixel radius.
    return win?.viewport.zoom ?? 1;
  }
}
