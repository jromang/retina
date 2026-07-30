// Desktop — a free surface on which to drop process instances.
//
// **Free** and persisted positions, as in the Qt shell: the user arranges their icons as they
// see fit, and finds them again at the next session. They do not live in an interface setting
// but in the library entry itself (`app.library.move`), so they follow the entry if it is
// renamed.
//
// Gestures carried over identically from ``gui/desktop_panel.py``:
//   drag                  → move (persisted on release)
//   Ctrl + drag           → external drag, onto a view or the Library
//   double-click          → open the pre-filled form
//   right-click           → context menu
//   right-click on the bg → "Tidy up the icons"

import { useEffect, useRef, useState } from 'preact/hooks';

import { client } from '../api/client';
import {
  carriesAnything,
  readDragPayload,
} from '../dnd/dnd';
import {
  startEntryDrag,
  storeDroppedPayload,
  useLibrary,
  type LibraryEntry,
} from '../panels/LibraryPanel';
import { m } from '../paraglide/messages';
import { openContainerFromLibrary } from '../pipeline/containerEdit';
import { runContainer, runProcess } from '../processes/jobs';
import { promptText } from '../ui/prompts';

const GRID = 96;
const ICON = 72;
const COLUMNS = 7;

interface Menu {
  x: number;
  y: number;
  entry: LibraryEntry | null;
}

export function DesktopTab() {
  const [entries] = useLibrary();
  const hostRef = useRef<HTMLDivElement>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [over, setOver] = useState(false);
  // Position during a drag — the server state is only updated on release, otherwise an XML
  // file would be written for every pixel travelled.
  const [dragging, setDragging] = useState<{ name: string; x: number; y: number } | null>(null);

  useEffect(() => {
    const close = () => setMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, []);

  /** Display position: provisional during the drag, otherwise the server's. */
  const positionOf = (entry: LibraryEntry, index: number): [number, number] => {
    if (dragging?.name === entry.name) return [dragging.x, dragging.y];
    if (entry.position) return [entry.position[0], entry.position[1]];
    // Never placed: we lay it out on a grid without persisting anything — it is a default
    // display, not a decision of the user's.
    return [24 + (index % COLUMNS) * GRID, 24 + Math.floor(index / COLUMNS) * GRID];
  };

  const onIconPointerDown = (event: PointerEvent, entry: LibraryEntry, index: number) => {
    if (event.button !== 0 || event.ctrlKey) return; // Ctrl = external drag (HTML5)
    event.preventDefault();
    const host = hostRef.current;
    if (!host) return;
    const bounds = host.getBoundingClientRect();
    const [x0, y0] = positionOf(entry, index);
    const grabX = event.clientX - bounds.left - x0;
    const grabY = event.clientY - bounds.top - y0;

    const move = (e: PointerEvent) => {
      setDragging({
        name: entry.name,
        x: Math.max(0, e.clientX - bounds.left - grabX),
        y: Math.max(0, e.clientY - bounds.top - grabY),
      });
    };
    const up = (e: PointerEvent) => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      const x = Math.max(0, e.clientX - bounds.left - grabX);
      const y = Math.max(0, e.clientY - bounds.top - grabY);
      setDragging(null);
      if (Math.abs(x - x0) > 2 || Math.abs(y - y0) > 2) {
        void client
          .call('library.set_position', { name: entry.name, x, y })
          .catch((error: unknown) => console.error(error));
      }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const arrange = () => {
    entries.forEach((entry, index) => {
      void client
        .call('library.set_position', {
          name: entry.name,
          x: 24 + (index % COLUMNS) * GRID,
          y: 24 + Math.floor(index / COLUMNS) * GRID,
        })
        .catch(() => undefined);
    });
  };

  const onDrop = (event: DragEvent) => {
    setOver(false);
    const transfer = event.dataTransfer;
    const host = hostRef.current;
    if (!transfer || !host) return;
    event.preventDefault();
    const payload = readDragPayload(transfer);
    if (!payload) return;
    if (payload.name) return; // already comes from the Desktop: the move is handled by pointer
    storeDroppedPayload(payload, payload.processes[0]?.process_id ?? 'instance');
  };

  return (
    <div
      ref={hostRef}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        overflow: 'auto',
        background: 'var(--vscode-editor-background)',
        outline: over ? '2px dashed var(--retina-drop-legal)' : 'none',
        outlineOffset: '-4px',
      }}
      onDragOver={(event) => {
        const transfer = (event as DragEvent).dataTransfer;
        if (!transfer || !carriesAnything(transfer)) return;
        event.preventDefault();
        transfer.dropEffect = 'copy';
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      onContextMenu={(event) => {
        event.preventDefault();
        const bounds = hostRef.current?.getBoundingClientRect();
        setMenu({
          x: event.clientX - (bounds?.left ?? 0),
          y: event.clientY - (bounds?.top ?? 0),
          entry: null,
        });
      }}
    >
      {entries.length === 0 && (
        <p
          style={{
            color: 'var(--vscode-descriptionForeground)',
            padding: '24px',
            margin: 0,
            fontSize: '13px',
          }}
        >
          {m.desktop_empty()}
        </p>
      )}

      {entries.map((entry, index) => {
        const [x, y] = positionOf(entry, index);
        return (
          <div
            key={entry.name}
            draggable
            title={
              entry.kind === 'container'
                ? (entry.process_ids ?? []).join(' → ')
                : entry.process_id
            }
            style={{
              position: 'absolute',
              left: `${x}px`,
              top: `${y}px`,
              width: `${ICON}px`,
              display: 'grid',
              justifyItems: 'center',
              gap: '2px',
              padding: '4px',
              borderRadius: '3px',
              cursor: 'grab',
              userSelect: 'none',
              background:
                dragging?.name === entry.name ? 'var(--vscode-list-hoverBackground)' : 'none',
            }}
            onPointerDown={(event) => onIconPointerDown(event as PointerEvent, entry, index)}
            onDragStart={(event) => {
              const transfer = (event as DragEvent).dataTransfer;
              if (transfer) void startEntryDrag(transfer, entry);
            }}
            onDblClick={() => openEntry(entry)}
            onContextMenu={(event) => {
              event.preventDefault();
              event.stopPropagation();
              const bounds = hostRef.current?.getBoundingClientRect();
              setMenu({
                x: event.clientX - (bounds?.left ?? 0),
                y: event.clientY - (bounds?.top ?? 0),
                entry,
              });
            }}
          >
            <i
              class={`codicon codicon-${entry.kind === 'container' ? 'list-ordered' : 'symbol-method'}`}
              style={{ fontSize: '28px', color: 'var(--vscode-charts-blue)' }}
              aria-hidden="true"
            />
            <span
              style={{
                fontSize: '11px',
                textAlign: 'center',
                wordBreak: 'break-word',
                lineHeight: 1.2,
              }}
            >
              {entry.name}
            </span>
          </div>
        );
      })}

      {menu && (
        <div
          style={{
            position: 'absolute',
            left: `${menu.x}px`,
            top: `${menu.y}px`,
            background: 'var(--vscode-editorWidget-background)',
            border: '1px solid var(--vscode-editorWidget-border)',
            borderRadius: '3px',
            boxShadow: '0 4px 12px var(--vscode-widget-shadow)',
            padding: '4px 0',
            minWidth: '180px',
            zIndex: 20,
          }}
        >
          {menu.entry ? (
            <>
              <MenuItem
                label={m.desktop_apply_active()}
                onClick={() => applyEntry(menu.entry!)}
              />
              <MenuItem label={m.desktop_open()} onClick={() => openEntry(menu.entry!)} />
              <MenuItem
                label={m.desktop_rename()}
                onClick={() => {
                  const current = menu.entry!.name;
                  void promptText(
                    m.desktop_rename_prompt(),
                    current,
                    m.desktop_rename_confirm(),
                  ).then((next) => {
                    if (next && next !== current) {
                      void client
                        .call('library.rename', { old: current, new: next })
                        .catch(() => undefined);
                    }
                  });
                }}
              />
              <MenuItem
                label={m.prompt_delete()}
                onClick={() => {
                  void client
                    .call('library.delete', { name: menu.entry!.name })
                    .catch(() => undefined);
                }}
              />
            </>
          ) : (
            <MenuItem label={m.desktop_arrange()} onClick={arrange} />
          )}
        </div>
      )}
    </div>
  );
}

function MenuItem({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        background: 'none',
        border: 'none',
        color: 'var(--vscode-foreground)',
        font: '13px var(--retina-font-ui)',
        padding: '4px 12px',
        cursor: 'pointer',
      }}
      onMouseEnter={(event) => {
        (event.currentTarget as HTMLElement).style.background =
          'var(--vscode-list-hoverBackground)';
      }}
      onMouseLeave={(event) => {
        (event.currentTarget as HTMLElement).style.background = 'none';
      }}
    >
      {label}
    </button>
  );
}

/** Open the entry: a form for an instance, the recipe editor for a container. */
function openEntry(entry: LibraryEntry): void {
  if (entry.kind === 'container') {
    void openContainerFromLibrary(entry.name).catch((error: unknown) => console.error(error));
    return;
  }
  if (entry.process_id) {
    void client
      .call('layout.open_process', { process_id: entry.process_id })
      .catch(() => undefined);
  }
}

/** Apply the entry to the active view — the context menu's shortcut. */
function applyEntry(entry: LibraryEntry): void {
  void client
    .call<{ processes: Array<{ process_id: string; values: Record<string, unknown> }> }>(
      'library.get',
      { name: entry.name },
    )
    .then((detail) => {
      // A recipe leaves as **one** ordered job: the earlier `process.run` loop released N
      // concurrent jobs on a pool of four threads, with no guarantee of sequence.
      if (entry.kind === 'container') {
        void runContainer(detail.processes, undefined, entry.name).catch((error: unknown) =>
          console.error(error),
        );
        return;
      }
      for (const process of detail.processes) {
        void runProcess(process.process_id, process.values).catch((error: unknown) =>
          console.error(error),
        );
      }
    })
    .catch((error: unknown) => console.error(error));
}
