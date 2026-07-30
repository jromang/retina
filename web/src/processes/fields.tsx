// Form fields derived from the ``Parameter`` schema — web equivalent of
// ``gui/panels.py::_widget_for``.
//
// No process has a hand-written form: all 115 (and those a third-party package will add
// through an entry-point) are rendered from their parameter table. That is what makes the
// catalogue extensible without touching the interface.
//
// Actual distribution of the catalogue's 314 parameters, which dictates where to put the
// effort:
//   real 129 · int 69 · str 37 · enum 32 · bool 18 · path 11 · pathlist 9
//   floatlist 4 · text 2 · intlist 1 · points 1 · pointlist 1

import { useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import type { ParameterMeta } from '../api/types';
import { askPath } from '../shell/native';
import { CurveEditor } from './CurveEditor';
import { MonacoField, PathListEditor } from './editors';

export interface FieldProps {
  param: ParameterMeta;
  value: unknown;
  onChange: (value: unknown) => void;
}

/**
 * Is a field visible, given the form's current values?
 *
 * `visible_when` designates another field and the values that make this one appear — thus
 * `BackgroundExtraction` only shows the photutils settings under its like-named backend, and
 * the model selector only under the `ai` backend. Without a clause, always visible. The
 * comparison goes through `String()`: the controller is an `enum` (hence a string), and
 * aligning on that avoids a false negative should a value arrive as a number.
 */
export function isVisible(param: ParameterMeta, values: Record<string, unknown>): boolean {
  const cond = param.visible_when;
  if (!cond) return true;
  return cond.values.some((v) => String(v) === String(values[cond.param]));
}

const inputStyle = {
  width: '100%',
  background: 'var(--vscode-input-background)',
  color: 'var(--vscode-input-foreground)',
  border: '1px solid var(--vscode-input-border)',
  borderRadius: '2px',
  padding: '2px 6px',
  font: '12px var(--retina-font-mono)',
  outline: 'none',
} as const;

/**
 * Numeric field — 198 of the 314 parameters go through it, so it has to be excellent.
 *
 * Horizontal dragging ("scrub") avoids the keyboard round trip when hunting for a value by
 * eye: you drag, the preview follows. It is the gesture of compositing software, and it makes
 * micro-adjustments far faster than a text field.
 */
export function NumberField({ param, value, onChange }: FieldProps) {
  const isInt = param.type === 'int';
  const numeric = typeof value === 'number' ? value : Number(param.default ?? 0);
  const [text, setText] = useState<string | null>(null);
  const dragRef = useRef<{ startX: number; startValue: number } | null>(null);

  const bounded = param.min !== null && param.max !== null;
  const step = isInt ? 1 : bounded ? (param.max! - param.min!) / 200 : 0.01;

  const clamp = (raw: number): number => {
    let next = isInt ? Math.round(raw) : raw;
    if (param.min !== null) next = Math.max(param.min, next);
    if (param.max !== null) next = Math.min(param.max, next);
    return next;
  };

  const commit = (raw: number) => {
    if (Number.isFinite(raw)) onChange(clamp(raw));
  };

  const onPointerDown = (event: PointerEvent) => {
    if (event.button !== 0) return;
    dragRef.current = { startX: event.clientX, startValue: numeric };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    event.preventDefault();
    // Shift = fine adjustment (×0.1): the same gesture serves coarse and precise alike.
    const scale = event.shiftKey ? 0.1 : 1;
    commit(drag.startValue + (event.clientX - drag.startX) * step * scale);
  };

  const onPointerUp = (event: PointerEvent) => {
    dragRef.current = null;
    (event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId);
  };

  const display = text ?? (isInt ? String(numeric) : String(Number(numeric.toFixed(6))));
  const ratio =
    bounded && param.max! > param.min!
      ? (numeric - param.min!) / (param.max! - param.min!)
      : null;

  return (
    <div>
      <input
        type="text"
        inputMode="decimal"
        value={display}
        title={`${param.tooltip}\n${m.field_scrub_hint()}`}
        style={{ ...inputStyle, cursor: 'ew-resize' }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onInput={(e) => setText((e.target as HTMLInputElement).value)}
        onBlur={(e) => {
          commit(Number((e.target as HTMLInputElement).value.replace(',', '.')));
          setText(null);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            commit(Number((e.target as HTMLInputElement).value.replace(',', '.')));
            setText(null);
          } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            e.preventDefault();
            commit(numeric + (e.key === 'ArrowUp' ? step : -step) * (e.shiftKey ? 0.1 : 1));
            setText(null);
          }
        }}
      />
      {ratio !== null && (
        // A position track, not a slider: it informs without adding a second click target,
        // the adjustment being made by dragging on the field itself.
        <div style={{ height: '2px', background: 'var(--vscode-input-border)', marginTop: '2px' }}>
          <div
            style={{
              height: '100%',
              width: `${Math.max(0, Math.min(1, ratio)) * 100}%`,
              background: 'var(--vscode-progressBar-background)',
            }}
          />
        </div>
      )}
    </div>
  );
}

export function BoolField({ param, value, onChange }: FieldProps) {
  return (
    <input
      type="checkbox"
      checked={Boolean(value)}
      title={param.tooltip}
      onChange={(e) => onChange((e.target as HTMLInputElement).checked)}
    />
  );
}

export function StrField({ param, value, onChange }: FieldProps) {
  return (
    <input
      type="text"
      value={String(value ?? '')}
      title={param.tooltip}
      style={inputStyle}
      onInput={(e) => onChange((e.target as HTMLInputElement).value)}
    />
  );
}

export function EnumField({ param, value, onChange }: FieldProps) {
  return (
    <select
      value={String(value ?? '')}
      title={param.tooltip}
      style={{ ...inputStyle, font: '12px var(--retina-font-ui)' }}
      onChange={(e) => onChange((e.target as HTMLSelectElement).value)}
    >
      {(param.choices ?? []).map((choice) => (
        <option key={choice} value={choice}>
          {choice}
        </option>
      ))}
    </select>
  );
}

const browseStyle = {
  background: 'var(--vscode-button-secondaryBackground)',
  color: 'var(--vscode-button-secondaryForeground)',
  border: 'none',
  borderRadius: '2px',
  padding: '0 8px',
  cursor: 'pointer',
} as const;

/** File path — native dialog in the shell, manual entry in a browser. */
export function PathField({ param, value, onChange }: FieldProps) {
  return (
    <div style={{ display: 'flex', gap: '4px' }}>
      <StrField param={param} value={value} onChange={onChange} />
      <button
        title={m.field_browse()}
        style={browseStyle}
        onClick={() => {
          void askPath({ title: param.label }).then((paths) => {
            if (paths?.[0]) onChange(paths[0]);
          });
        }}
      >
        …
      </button>
    </div>
  );
}

/**
 * Folder — same field as `path`, but the native dialog opens in directory mode.
 *
 * The type exists for the preferences: "where to write the temporaries" has no file filter,
 * and offering a file picker to choose a folder is the kind of detail that casts doubt on
 * everything else.
 */
export function DirField({ param, value, onChange }: FieldProps) {
  return (
    <div style={{ display: 'flex', gap: '4px' }}>
      <StrField param={param} value={value} onChange={onChange} />
      <button
        title={m.field_browse()}
        style={browseStyle}
        onClick={() => {
          void askPath({ title: param.label, folder: true }).then((paths) => {
            if (paths?.[0]) onChange(paths[0]);
          });
        }}
      >
        …
      </button>
    </div>
  );
}

/** Lists (pathlist, floatlist, intlist) — one entry per line, converted on blur. */
export function ListField({ param, value, onChange }: FieldProps) {
  const numeric = param.type !== 'pathlist';
  const items = Array.isArray(value) ? value : [];
  return (
    <div style={{ display: 'grid', gap: '3px' }}>
    {!numeric && (
      // This is the field of the global processes: dozens of raw frames are added at once,
      // typing them by hand would be absurd.
      <button
        style={{ ...browseStyle, justifySelf: 'start', padding: '2px 8px', fontSize: '11px' }}
        onClick={() => {
          void askPath({ title: param.label, multiple: true }).then((paths) => {
            if (paths?.length) onChange([...items, ...paths]);
          });
        }}
      >
        {m.field_add_files()}
      </button>
    )}
    <textarea
      rows={Math.min(8, Math.max(2, items.length + 1))}
      value={items.join('\n')}
      title={`${param.tooltip}\n${m.field_one_per_line()}`}
      style={{ ...inputStyle, resize: 'vertical' }}
      onBlur={(e) => {
        const lines = (e.target as HTMLTextAreaElement).value
          .split('\n')
          .map((line) => line.trim())
          .filter(Boolean);
        onChange(numeric ? lines.map(Number).filter((n) => Number.isFinite(n)) : lines);
      }}
    />
    </div>
  );
}

/** Code (PixelMath). Pending Monaco, a monospace area does the job. */
export function TextField({ param, value, onChange }: FieldProps) {
  return (
    <textarea
      rows={4}
      value={String(value ?? '')}
      title={param.tooltip}
      style={{ ...inputStyle, resize: 'vertical' }}
      onInput={(e) => onChange((e.target as HTMLTextAreaElement).value)}
    />
  );
}

/**
 * Types with no dedicated editor (``points``, ``pointlist``) — a single process concerned by
 * each.
 *
 * Displays the value and points to the console rather than inventing a JSON editor: that is
 * the fallback the Qt shell already had ("edit from the console"), and the curve editor is
 * coming.
 */
export function UnsupportedField({ param, value }: FieldProps) {
  return (
    <div
      style={{
        font: '11px var(--retina-font-mono)',
        color: 'var(--vscode-descriptionForeground)',
        padding: '2px 0',
      }}
      title={m.field_no_editor({ type: param.type })}
    >
      {JSON.stringify(value)} <span style={{ opacity: 0.7 }}>{m.field_edit_in_console()}</span>
    </div>
  );
}

/** Type → component switch. The only place that knows the mapping. */
export function fieldFor(type: string): (props: FieldProps) => preact.JSX.Element {
  switch (type) {
    case 'real':
    case 'int':
      return NumberField;
    case 'bool':
      return BoolField;
    case 'enum':
      return EnumField;
    case 'str':
      return StrField;
    case 'path':
      return PathField;
    case 'dir':
      return DirField;
    case 'pathlist':
      return PathListEditor;
    case 'floatlist':
    case 'intlist':
      return ListField;
    case 'text':
      return MonacoField;
    case 'points':
      return CurveEditor;
    default:
      return UnsupportedField;
  }
}
