// Custom Blink panel — scrolling through raw frames to sort them by eye.
//
// The core (`processes/inspection.py`) says itself that "a GUI panel will only have to
// display `current_image()`". That is exactly what this does, and nothing more: navigation,
// caching and statistics live in the domain, this panel is only a remote control.
//
// No new event channel: each step replaces the pixels of the Blink window, which advances its
// generation, restarts the snapshot and reloads the viewport texture.
//
// **Dropping here means dropping from the project.** Blink looks at raw frames before any
// measurement: what is removed is a file that has no business being in the batch, hence
// `pipeline.exclude`, which takes it out of the whole chain. Not to be confused with the frame
// selector's rejection, which judges after measurement and merely refrains from stacking the
// exposure.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { plural } from '../ui/plural';
import { client } from '../api/client';
import { inventory, setExcluded } from '../pipeline/model';
import type { CustomPanelProps } from './customPanels';

/** Cadence of the automatic scroll — slow enough to see, brisk enough to compare. */
const AUTO_INTERVAL_MS = 600;

interface BlinkState {
  index: number;
  count: number;
  frames: string[];
  window: string | null;
  stats: { name?: string; median?: number; min?: number; max?: number; shape?: number[] };
}

const buttonStyle = {
  background: 'var(--vscode-button-secondaryBackground)',
  color: 'var(--vscode-button-secondaryForeground)',
  border: 'none',
  borderRadius: '2px',
  padding: '3px 8px',
  fontSize: '11px',
  cursor: 'pointer',
} as const;

const MUTED = 'var(--vscode-descriptionForeground)';

export function BlinkPanel({ values }: CustomPanelProps) {
  const frames = Array.isArray(values['frames']) ? (values['frames'] as string[]) : [];
  const [state, setState] = useState<BlinkState | null>(null);
  const [auto, setAuto] = useState(false);
  const [error, setError] = useState('');
  const hostRef = useRef<HTMLDivElement>(null);

  const call = (method: string, params: Record<string, unknown> = {}) =>
    client
      .call<BlinkState | null>(method, params)
      .then((etat) => {
        setState(etat);
        setError('');
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));

  const ouvrir = () => void call('app.blink', { frames });
  const pas = (delta: number) => void call('app.blink_step', { delta });
  const aller = (index: number) => void call('app.blink_go_to', { index });

  // A sequence may have been opened from the console: we adopt its state rather than show an
  // empty panel next to a window that is scrolling.
  useEffect(() => {
    void call('app.blink_state');
  }, []);

  // Automatic cadence. An interval rather than an animation loop: what is wanted is a steady
  // comparison rhythm, not the screen's refresh rate.
  useEffect(() => {
    if (!auto || !state?.count) return;
    const timer = window.setInterval(() => pas(1), AUTO_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [auto, state?.count]);

  // The keyboard only acts if the panel has focus: the arrows serve elsewhere (trees, fields),
  // and capturing them globally would break navigation in the rest of the shell.
  const onKeyDown = (event: KeyboardEvent) => {
    const pasParTouche: Record<string, number> = {
      ArrowRight: 1,
      ArrowDown: 1,
      ArrowLeft: -1,
      ArrowUp: -1,
      PageDown: 5,
      PageUp: -5,
    };
    const delta = pasParTouche[event.key];
    if (delta !== undefined) {
      event.preventDefault();
      pas(delta);
    } else if (event.key === ' ') {
      event.preventDefault();
      setAuto(!auto);
    }
  };

  const courante = state?.frames[state.index] ?? '';
  // The exclusion gesture only makes sense on a frame the project knows about: the wizard's
  // inventory is the only thing that can take it out of the chain.
  const dansLeProjet = (inventory.value?.frames ?? []).some((f) => f.path === courante);
  const dejaEcartee = (inventory.value?.frames ?? []).some(
    (f) => f.path === courante && f.excluded,
  );

  return (
    <div
      ref={hostRef}
      tabIndex={0}
      data-focus-ring
      onKeyDown={onKeyDown}
      title={m.blink_focus_tip()}
      style={{ display: 'grid', gap: '6px', marginBottom: '8px' }}
    >
      <div style={{ display: 'flex', gap: '4px', alignItems: 'center', flexWrap: 'wrap' }}>
        <button style={buttonStyle} disabled={!frames.length} onClick={ouvrir}>
          {m.blink_open_sequence()}
        </button>
        <button style={buttonStyle} disabled={!state?.count} onClick={() => pas(-1)}>
          ◀
        </button>
        <button style={buttonStyle} disabled={!state?.count} onClick={() => pas(1)}>
          ▶
        </button>
        <button
          style={{
            ...buttonStyle,
            background: auto
              ? 'var(--vscode-button-background)'
              : 'var(--vscode-button-secondaryBackground)',
            color: auto ? 'var(--vscode-button-foreground)' : undefined,
          }}
          disabled={!state?.count}
          title={m.blink_auto_tip()}
          onClick={() => setAuto(!auto)}
        >
          {auto ? '❚❚' : '▶▶'}
        </button>
        <span style={{ marginLeft: 'auto', fontSize: '11px', color: MUTED }}>
          {state?.count
            ? `${state.index + 1} / ${state.count}`
            : plural(
                frames.length,
                m.blink_frame_one({ count: frames.length }),
                m.blink_frame_many({ count: frames.length }),
              )}
        </span>
      </div>

      {state?.count ? (
        <input
          type="range"
          min={0}
          max={state.count - 1}
          value={state.index}
          aria-label={m.blink_position()}
          onInput={(e) => aller(Number((e.target as HTMLInputElement).value))}
        />
      ) : null}

      {state?.stats?.name && (
        <div style={{ fontSize: '11px', color: MUTED, font: '11px var(--retina-font-mono)' }}>
          {m.blink_stats({
            name: state.stats.name,
            median: state.stats.median?.toFixed(5) ?? '',
            min: state.stats.min?.toFixed(5) ?? '',
            max: state.stats.max?.toFixed(5) ?? '',
          })}
        </div>
      )}

      {state?.count ? (
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          <button
            style={buttonStyle}
            disabled={!dansLeProjet}
            title={dansLeProjet ? m.blink_exclude_tip() : m.blink_not_in_project()}
            onClick={() => void setExcluded([courante], !dejaEcartee)}
          >
            {dejaEcartee ? m.blink_reinstate() : m.blink_exclude()}
          </button>
          <span style={{ fontSize: '11px', color: MUTED }}>{m.blink_keys_hint()}</span>
        </div>
      ) : null}

      {error && (
        <p style={{ margin: 0, fontSize: '11px', color: 'var(--vscode-errorForeground)' }}>
          {error}
        </p>
      )}

      <p style={{ margin: 0, fontSize: '11px', color: MUTED, lineHeight: 1.4 }}>
        {m.blink_hint_a()} <strong>{m.blink_hint_all()}</strong> {m.blink_hint_b()}{' '}
        <em>{m.panel_selector()}</em>.
      </p>
    </div>
  );
}
