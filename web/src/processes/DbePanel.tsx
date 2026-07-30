// Custom panel of DynamicBackgroundExtraction.
//
// Setting this process up does not fit in a form: one places **background samples** by
// clicking on the image, where there is no object. The Qt shell had the same special case,
// served by the same mechanism (`gui/panel_registry.py`).
//
// The registry of custom panels is in `customPanels.ts`; the auto-generated form covers all
// the rest of the catalogue.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { plural } from '../ui/plural';
import { client } from '../api/client';
import { activeView } from '../state/store';
import { armDynamicTool } from '../viewport/dynamicTool';
import type { CustomPanelProps } from './customPanels';

type Sample = [number, number];

/** Tag of the panel's overlays — so as to erase only ours. */
const TAG = 'dbe';

export function DbeSamples({ values, onChange }: CustomPanelProps) {
  const view = activeView.value;
  const samples: Sample[] = Array.isArray(values['samples'])
    ? (values['samples'] as Sample[])
    : [];
  const [placing, setPlacing] = useState(false);

  // The tool is rearmed on every change of `values` (the closure must see the current
  // samples), but the click must read the freshest state even without a rearm: a ref keeps a
  // fast click from overwriting the list with a stale version.
  const latest = useRef({ samples, values, onChange });
  latest.current = { samples, values, onChange };

  // Placement goes through the domain's interaction mode — it is what decides what a click
  // does — **and** through the client tool, which says what that click fills in. Without the
  // second, the `dynamic` mode was set and nothing listened to it: the panel could never
  // place anything.
  useEffect(() => {
    if (!placing) return;
    void client.call('app.set_interaction_mode', { mode: 'dynamic' }).catch(() => undefined);
    const disarm = armDynamicTool({
      id: 'dbe.samples',
      label: m.dbe_tool_label(),
      cursor: 'crosshair',
      onDown: ({ point }) => {
        const { samples: current, values: v, onChange: change } = latest.current;
        // Rounded: the parameter is a list of image points, and half a pixel makes no sense
        // for a background sample.
        change({ ...v, samples: [...current, [Math.round(point[0]), Math.round(point[1])]] });
      },
    });
    return () => {
      disarm();
      void client.call('app.set_interaction_mode', { mode: 'readout' }).catch(() => undefined);
    };
  }, [placing]);

  // The samples are drawn by the viewport, through the domain overlays: they are thus also
  // visible from the console, and not only here.
  //
  // `set_overlays` and not "clear then add": two RPCs are not ordered (the server handles them
  // as tasks), and two fast clicks left the first one's set of markers on screen. One call,
  // one mutation, nothing to reorder.
  useEffect(() => {
    if (!view) return;
    void client
      .call('app.set_overlays', {
        tag: TAG,
        overlays:
          samples.length > 0
            ? [{ kind: 'markers', points: samples, color: [0.2, 0.9, 1.0, 1.0], size: 9 }]
            : [],
      })
      .catch(() => undefined);
  }, [samples.length, view?.id]);

  // Closing the panel must not leave its markers on the image.
  useEffect(
    () => () => {
      void client.call('app.clear_overlays', { tag: TAG }).catch(() => undefined);
    },
    [],
  );

  const buttonStyle = {
    background: 'var(--vscode-button-secondaryBackground)',
    color: 'var(--vscode-button-secondaryForeground)',
    border: 'none',
    borderRadius: '2px',
    padding: '3px 8px',
    fontSize: '11px',
    cursor: 'pointer',
  } as const;

  return (
    <div style={{ display: 'grid', gap: '6px', marginBottom: '8px' }}>
      <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
        <button
          style={{
            ...buttonStyle,
            background: placing
              ? 'var(--vscode-button-background)'
              : 'var(--vscode-button-secondaryBackground)',
            color: placing ? 'var(--vscode-button-foreground)' : undefined,
          }}
          onClick={() => setPlacing(!placing)}
        >
          {placing ? m.dbe_placing() : m.dbe_place_samples()}
        </button>
        <button
          style={buttonStyle}
          disabled={samples.length === 0}
          onClick={() => onChange({ ...values, samples: [] })}
        >
          {m.dbe_clear()}
        </button>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '11px',
            color: 'var(--vscode-descriptionForeground)',
          }}
        >
          {plural(
            samples.length,
            m.dbe_sample_one({ count: samples.length }),
            m.dbe_sample_many({ count: samples.length }),
          )}
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
        {m.dbe_hint_a()} <strong>{m.dbe_hint_sky()}</strong>{m.dbe_hint_b()}
      </p>
    </div>
  );
}
