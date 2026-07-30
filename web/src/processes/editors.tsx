// Editors for the parameter types that deserve better than a text field.
//
// Two cases, both tied to a precise use in the catalogue:
//   `text`     → PixelMath, where one writes Python: Monaco, with highlighting and completion.
//   `pathlist` → the global processes (Integration & co), where one stacks dozens of raw
//                frames: a virtualised list, a counter, and the total volume.

import { useEffect, useMemo, useRef, useState } from 'preact/hooks';

import { askPath } from '../shell/native';
import type { FieldProps } from './fields';
import { m } from '../paraglide/messages';

// --- PixelMath ---------------------------------------------------------------
const CODE_HEIGHT = 130;

/**
 * Code field — Monaco, loaded on demand.
 *
 * This is the net gain over the Qt shell, which makes do with static Pygments highlighting:
 * here we get indentation, block selection and folding, on an editor that had already been
 * loaded for the console.
 */
export function MonacoField({ param, value, onChange }: FieldProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<{ dispose: () => void; getValue: () => string } | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    const host = hostRef.current;
    if (!host || editorRef.current) return;
    let disposed = false;

    void import('../console/monaco').then(({ setupMonaco }) => {
      if (disposed) return;
      const monaco = setupMonaco();
      const editor = monaco.editor.create(host, {
        value: String(value ?? ''),
        language: 'python',
        theme: 'retina-dark',
        automaticLayout: true,
        minimap: { enabled: false },
        lineNumbers: 'on',
        lineNumbersMinChars: 2,
        glyphMargin: false,
        folding: false,
        scrollBeyondLastLine: false,
        overviewRulerLanes: 0,
        fontSize: 12,
        fontFamily: 'var(--retina-font-mono)',
        wordWrap: 'on',
        contextmenu: false,
      });
      // Reported on blur, not on keystroke: a PixelMath expression is incomplete while it is
      // being typed, and triggering a preview on every character would make no sense.
      editor.onDidBlurEditorText(() => onChangeRef.current(editor.getValue()));
      editorRef.current = editor;
    });

    return () => {
      disposed = true;
      editorRef.current?.dispose();
      editorRef.current = null;
    };
  }, []);

  return (
    <div
      ref={hostRef}
      title={param.tooltip}
      style={{
        height: `${CODE_HEIGHT}px`,
        border: '1px solid var(--vscode-input-border)',
        borderRadius: '2px',
        overflow: 'hidden',
      }}
    />
  );
}

// --- file lists --------------------------------------------------------------
const ROW_HEIGHT = 20;
const VIEWPORT_ROWS = 9;
/** Beyond that, only the visible window is rendered: 400 raw frames means 400 DOM nodes. */
const VIRTUALISE_ABOVE = 60;

export function PathListEditor({ param, value, onChange }: FieldProps) {
  const items: string[] = Array.isArray(value) ? value.map(String) : [];
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [scrollTop, setScrollTop] = useState(0);
  const height = Math.min(items.length || 1, VIEWPORT_ROWS) * ROW_HEIGHT;

  const window = useMemo(() => {
    if (items.length <= VIRTUALISE_ABOVE) return { start: 0, rows: items };
    const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - 2);
    return { start, rows: items.slice(start, start + VIEWPORT_ROWS + 4) };
  }, [items, scrollTop]);

  const add = () => {
    void askPath({ title: param.label, multiple: true }).then((paths) => {
      if (paths?.length) onChange([...items, ...paths]);
    });
  };

  const removeSelected = () => {
    if (selected.size === 0) return;
    onChange(items.filter((_, index) => !selected.has(index)));
    setSelected(new Set());
  };

  const toggle = (index: number, additive: boolean) => {
    const next = additive ? new Set(selected) : new Set<number>();
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setSelected(next);
  };

  const onDrop = (event: DragEvent) => {
    // Files dropped from the system explorer. In a browser, `File` does not give the path —
    // only the native shell can supply what `app` needs.
    event.preventDefault();
    const names = Array.from(event.dataTransfer?.files ?? [])
      .map((file) => (file as File & { path?: string }).path)
      .filter((path): path is string => Boolean(path));
    if (names.length) onChange([...items, ...names]);
  };

  const buttonStyle = {
    background: 'var(--vscode-button-secondaryBackground)',
    color: 'var(--vscode-button-secondaryForeground)',
    border: 'none',
    borderRadius: '2px',
    padding: '2px 8px',
    fontSize: '11px',
    cursor: 'pointer',
  } as const;

  return (
    <div style={{ display: 'grid', gap: '3px' }} onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
        <button style={buttonStyle} onClick={add}>
          {m.filelist_add()}
        </button>
        <button style={buttonStyle} onClick={removeSelected} disabled={selected.size === 0}>
          {m.filelist_remove()}
        </button>
        <button style={buttonStyle} onClick={() => onChange([])} disabled={items.length === 0}>
          {m.filelist_clear()}
        </button>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '11px',
            color: 'var(--vscode-descriptionForeground)',
          }}
        >
          {items.length} fichier{items.length > 1 ? 's' : ''}
        </span>
      </div>
      <div
        style={{
          height: `${height}px`,
          overflowY: 'auto',
          background: 'var(--vscode-input-background)',
          border: '1px solid var(--vscode-input-border)',
          borderRadius: '2px',
        }}
        onScroll={(event) => setScrollTop((event.currentTarget as HTMLElement).scrollTop)}
      >
        {items.length === 0 && (
          <p
            style={{
              margin: 0,
              padding: '3px 6px',
              fontSize: '11px',
              color: 'var(--vscode-descriptionForeground)',
            }}
          >
            {m.filelist_empty()}
          </p>
        )}
        <div style={{ height: `${items.length * ROW_HEIGHT}px`, position: 'relative' }}>
          {window.rows.map((path, offset) => {
            const index = window.start + offset;
            return (
              <div
                key={`${index}-${path}`}
                title={path}
                onClick={(event) => toggle(index, event.ctrlKey || event.shiftKey)}
                style={{
                  position: 'absolute',
                  top: `${index * ROW_HEIGHT}px`,
                  left: 0,
                  right: 0,
                  height: `${ROW_HEIGHT}px`,
                  lineHeight: `${ROW_HEIGHT}px`,
                  padding: '0 6px',
                  font: '11px var(--retina-font-mono)',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  direction: 'rtl', // keeps the file name visible, truncates the path's start
                  textAlign: 'left',
                  cursor: 'pointer',
                  background: selected.has(index)
                    ? 'var(--vscode-list-activeSelectionBackground)'
                    : 'none',
                }}
              >
                {path}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
