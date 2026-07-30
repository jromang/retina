// Status bar — enriched compared to the former Qt shell, which only displays coords/values/zoom.
//
// Two deliberate additions:
//   - an indicator of the **connection to the server**: in a client/server architecture, knowing
//     whether the domain answers is no longer obvious, and it is the first thing to look at when
//     the interface seems frozen;
//   - the channel and the zoom are **clickable**: these are the two settings one changes most
//     often, and taking them out of the viewport toolbar lightens it.

import { useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import type { WindowState } from '../api/types';
import { NotificationBell } from '../notifications/NotificationBell';
import { activeView, activeWindow, connection } from '../state/store';
import { formatCelestial } from '../viewport/celestial';
import { MASK_DISPLAY_MODES } from './commands';
import { JobsIndicator } from './JobsIndicator';
import { layoutLocked } from './layoutClient';
import { openPalette } from './uiState';
import type { ViewportStatus } from '../viewport/ViewportPanel';

const CHANNELS = [
  'rgb',
  'red',
  'green',
  'blue',
  'L',
  'cie_L',
  'cie_a',
  'cie_b',
  'hue',
  'saturation',
  'value',
  'intensity',
] as const;

const ZOOM_PRESETS: Array<[string, string, Record<string, unknown>]> = [
  [m.status_zoom_fit(), 'app.zoom_to_fit', {}],
  ['1:1', 'app.zoom_1_1', {}],
  [m.status_percent({ value: 200 }), 'app.set_zoom', { zoom: 2 }],
  [m.status_percent({ value: 50 }), 'app.set_zoom', { zoom: 0.5 }],
];

const STATE = {
  connecting: { label: m.status_connecting(), color: 'var(--vscode-charts-yellow)' },
  open: { label: m.status_open(), color: 'var(--vscode-charts-green)' },
  closed: { label: m.status_closed(), color: 'var(--vscode-charts-red)' },
} as const;


interface Props {
  status: ViewportStatus | null;
}

/** Probe sizes offered — odd, so that the probe is centered on the targeted pixel. */
const PROBE_SIZES = [1, 3, 5, 7, 9];

/**
 * Settings of the readout probe, in a popover.
 *
 * `ReadoutOptions` existed in the domain, was serialized in the snapshot, served by
 * `app.set_readout_options`… and had no path in the interface. The popover follows the pattern
 * of the viewport breadcrumb rather than adding a menu component: three settings are not
 * worth an infrastructure.
 */
function ReadoutOptions({ window: win }: { window: WindowState }) {
  const [open, setOpen] = useState(false);
  const readout = win.viewport.readout;

  return (
    <span style={{ position: 'relative' }}>
      <button
        class="status-item"
        title={m.status_probe_settings()}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {m.status_probe({ size: readout.probe_size })}
      </button>
      {open && (
        <div
          class="popover"
          onMouseLeave={() => setOpen(false)}
          style={{
            position: 'absolute',
            bottom: '100%',
            right: 0,
            zIndex: 40,
            minWidth: '190px',
            padding: '8px',
            display: 'grid',
            gap: '6px',
            background: 'var(--vscode-menu-background, #252526)',
            border: '1px solid var(--vscode-menu-border, #454545)',
            borderRadius: '3px',
            fontSize: '12px',
          }}
        >
          <label style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            {m.status_probe_size()}
            <select
              value={String(readout.probe_size)}
              onChange={(e) =>
                call('app.set_readout_options', {
                  probe_size: Number((e.target as HTMLSelectElement).value),
                })
              }
            >
              {PROBE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}×{size}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            {m.status_precision()}
            <input
              type="number"
              min={0}
              max={9}
              value={readout.precision}
              style={{ width: '52px' }}
              onChange={(e) =>
                call('app.set_readout_options', {
                  precision: Number((e.target as HTMLInputElement).value),
                })
              }
            />
          </label>
          <label style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            <input
              type="checkbox"
              checked={readout.show_loupe}
              onChange={(e) =>
                call('app.set_readout_options', {
                  show_loupe: (e.target as HTMLInputElement).checked,
                })
              }
            />
            {m.status_loupe()}
          </label>
        </div>
      )}
    </span>
  );
}

function call(method: string, params?: Record<string, unknown>): void {
  void client.call(method, params).catch((error: unknown) => console.error(method, error));
}

export function StatusBar({ status }: Props) {
  const win = activeWindow.value;
  const view = activeView.value;
  const state = STATE[connection.value];

  return (
    <footer class="status-bar">
      <span class="status-item" style={{ color: state.color }} title={m.status_server()}>
        ● {state.label}
      </span>
      <button class="status-item" onClick={openPalette} title={m.status_palette()}>
        <i class="codicon codicon-search" style={{ marginRight: '4px' }} aria-hidden="true" />
        {m.status_commands()}
      </button>
      {view && (
        <span class="status-item">
          {view.id}
          {view.is_preview ? (view.volatile ? ' ⚡' : ' 🔒') : ''}
        </span>
      )}
      {status?.cursor && (
        <span class="status-item">
          x={status.cursor.x.toFixed(1)} y={status.cursor.y.toFixed(1)}
        </span>
      )}
      {status?.celestial && (
        // The counterpart of the classic readout: on a plate-solved image, the position in the sky
        // is worth more than the position in the array — it is the one that compares to a catalog.
        <span class="status-item" title={m.status_celestial()}>
          {formatCelestial(status.celestial.ra, status.celestial.dec)}
        </span>
      )}
      {status?.values && (
        // Read from the server's float32, not from the client's float16: five decimals
        // would make no sense on degraded data. The number of decimals comes from
        // `ReadoutOptions.precision`, which was serialized without anyone reading it.
        <span class="status-item" title={m.status_values()}>
          {status.values.map((value) => value.toFixed(status.precision)).join('  ')}
        </span>
      )}
      {win && <ReadoutOptions window={win} />}
      <JobsIndicator />

      <span style={{ flex: 1 }} />

      {layoutLocked.value && (
        // A silent lock would be a trap: the panels refuse to move without saying
        // why. Clicking unlocks — the same call as the palette command.
        <button
          class="status-item"
          title={m.status_layout_locked()}
          onClick={() => call('layout.lock', { locked: false })}
        >
          <i class="codicon codicon-lock" aria-hidden="true" />
        </button>
      )}
      <NotificationBell />

      {win?.mask && (
        // Visible only when there is a mask: three permanently dead controls
        // would wear the bar out for nothing. `inactive` is surfaced because it is the trap —
        // a mask one sees but that the processes ignore.
        <>
          <button
            class="status-item"
            title={win.viewport.mask_visible ? m.status_mask_hide() : m.status_mask_show()}
            onClick={() => call('app.set_mask_visible', { visible: !win.viewport.mask_visible })}
          >
            <i
              class={`codicon codicon-${win.viewport.mask_visible ? 'eye' : 'eye-closed'}`}
              style={{ marginRight: '4px' }}
              aria-hidden="true"
            />
            {m.status_mask()}
          </button>
          <select
            class="status-item"
            value={win.viewport.mask_display_mode}
            title={m.status_mask_render()}
            onChange={(e) =>
              call('app.set_mask_display_mode', { mode: (e.target as HTMLSelectElement).value })
            }
            style={{ background: 'transparent', color: 'inherit', border: 'none' }}
          >
            {MASK_DISPLAY_MODES.map(([mode, label]) => (
              <option key={mode} value={mode} style={{ color: 'black' }}>
                {label}
              </option>
            ))}
          </select>
          <button
            class="status-item"
            title={m.status_mask_invert()}
            onClick={() => call('app.set_mask_inverted', { inverted: !win.mask!.inverted })}
            style={{ opacity: win.mask.inverted ? 1 : 0.6 }}
          >
            {m.status_mask_inv()}
          </button>
          {!win.mask.enabled && (
            <span
              class="status-item"
              style={{ color: 'var(--vscode-charts-yellow)' }}
              title={m.status_mask_inactive_tip()}
            >
              {m.status_mask_inactive()}
            </span>
          )}
        </>
      )}
      {win && (
        <select
          class="status-item"
          value={win.viewport.channel}
          title={m.status_channel()}
          onChange={(e) =>
            call('app.set_display_channel', { channel: (e.target as HTMLSelectElement).value })
          }
          style={{ background: 'transparent', color: 'inherit', border: 'none' }}
        >
          {CHANNELS.map((channel) => (
            <option key={channel} value={channel} style={{ color: 'black' }}>
              {channel}
            </option>
          ))}
        </select>
      )}
      {win && (
        <button
          class="status-item"
          title={m.status_stf()}
          onClick={() => call('app.set_stf_enabled', { enabled: !win.viewport.stf_enabled })}
        >
          STF {win.viewport.stf_enabled ? 'on' : 'off'}
        </button>
      )}
      {status && win && (
        <select
          class="status-item"
          value=""
          title={m.status_zoom()}
          onChange={(e) => {
            const index = Number((e.target as HTMLSelectElement).value);
            const preset = ZOOM_PRESETS[index];
            if (preset) call(preset[1], preset[2]);
            (e.target as HTMLSelectElement).value = '';
          }}
          style={{ background: 'transparent', color: 'inherit', border: 'none' }}
        >
          <option value="">{m.status_percent({ value: Math.round(status.zoom * 100) })}</option>
          {ZOOM_PRESETS.map(([label], index) => (
            <option key={label} value={index} style={{ color: 'black' }}>
              {label}
            </option>
          ))}
        </select>
      )}
      {status && (
        <span class="status-item" style={{ opacity: 0.75 }} title={status.gpu}>
          {status.gpu.slice(0, 26)}
        </span>
      )}
    </footer>
  );
}
