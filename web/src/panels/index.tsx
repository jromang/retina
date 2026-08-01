// Content of the sidebar, right-zone and bottom-zone panels.
//
// All of them derive from the server snapshot: they hold no state of their own. A click calls
// an RPC, the server rebroadcasts, the UI follows. That is what guarantees that the same
// gesture typed in the console produces exactly the same visual result.
//
// The panels that cost nothing to implement for real (windows, history, explorer, STF) are
// functional; those that need a milestone of their own (doc, desktop, RTP) honestly announce
// what they are waiting for.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { plural } from '../ui/plural';
import { client } from '../api/client';
import type { ProcessMeta, ViewState, WindowState } from '../api/types';
import { TablerIcon } from '../shell/TablerIcon';
import { ChatPanel } from '../chat/ChatPanel';
import { ConsolePanel } from '../console/ConsolePanel';
import { newContainer, setSteps, type RecipeStep } from '../pipeline/containerEdit';
import { FilesPanel } from './FilesPanel';
import { HeaderPanel } from './HeaderPanel';
import { LibraryPanel } from './LibraryPanel';
import { StfPanel } from './StfPanel';
import {
  activeView,
  processes as processCatalog,
  processesByCategory,
  windows,
} from '../state/store';
import { ParameterGrid } from '../processes/ParameterGrid';
import { saveImageAs } from '../shell/saveImage';
import { useTreeNav } from '../ui/treeNav';
import { processRows, rowWindow, type ProcessRow } from './processRows';
import { openContextMenu, type ContextMenuNode } from '../ui/ContextMenu';
import { promptText } from '../ui/prompts';
import type { PanelId } from '../shell/panels';

function call(method: string, params?: Record<string, unknown>): void {
  void client.call(method, params).catch((error: unknown) => console.error(method, error));
}

/**
 * Hover card — an enriched tooltip, not a system.
 *
 * With 115 processes whose names are sometimes opaque (`B3Estimator`, `SCNR`), knowing what
 * they do without opening their form saves time in every session. The 500 ms delay keeps it
 * from flickering while scanning down the list.
 */
function HoverCard({ process, x, y }: { process: ProcessMeta; x: number; y: number }) {
  return (
    <div
      style={{
        position: 'fixed',
        left: `${x + 12}px`,
        top: `${y}px`,
        zIndex: 50,
        maxWidth: '280px',
        pointerEvents: 'none',
        background: 'var(--vscode-editorWidget-background)',
        border: '1px solid var(--vscode-editorWidget-border)',
        borderRadius: '3px',
        boxShadow: '0 4px 12px var(--vscode-widget-shadow)',
        padding: '6px 10px',
        fontSize: '12px',
      }}
    >
      <strong>{process.process_id}</strong>
      <div style={{ color: 'var(--vscode-descriptionForeground)', fontSize: '11px' }}>
        {process.category} ·{' '}
        {plural(
          process.parameters.length,
          m.panels_param({ count: process.parameters.length }),
          m.panels_params({ count: process.parameters.length }),
        )}
        {process.is_global && ` · ${m.panels_global()}`}
        {process.supports_realtime && ` · ${m.panels_realtime()}`}
        {process.is_maskable && ` · ${m.panels_maskable()}`}
      </div>
      {process.has_doc && (
        <div style={{ color: 'var(--vscode-descriptionForeground)', fontSize: '11px' }}>
          {m.panels_f1_doc()}
        </div>
      )}
    </div>
  );
}

// --- Process explorer --------------------------------------------------------
/** Height imposed on rows AND on headers: arithmetic windowing demands known heights,
 *  and `.tree-group` has a different padding by default. */
const PROCESS_ROW_HEIGHT = 22;

function ProcessExplorer() {
  const [query, setQuery] = useState('');
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(600);
  const [hover, setHover] = useState<{ process: ProcessMeta; x: number; y: number } | null>(null);
  const hoverTimer = useRef<number | undefined>(undefined);
  const scrollerRef = useRef<HTMLDivElement>(null);

  const rows = processRows(processesByCategory.value, query);
  const { start, end } = rowWindow(scrollTop, viewportHeight, rows.length, PROCESS_ROW_HEIGHT);

  const scheduleHover = (process: ProcessMeta, event: MouseEvent) => {
    globalThis.clearTimeout(hoverTimer.current);
    const { clientX, clientY } = event;
    hoverTimer.current = globalThis.setTimeout(
      () => setHover({ process, x: clientX, y: clientY }),
      500,
    );
  };

  const cancelHover = () => {
    globalThis.clearTimeout(hoverTimer.current);
    setHover(null);
  };

  const open = (row: ProcessRow | undefined) => {
    if (!row || row.kind !== 'item') return;
    cancelHover();
    call('layout.open_process', { process_id: row.process.process_id });
  };

  const nav = useTreeNav({
    idPrefix: 'process-tree',
    label: m.panel_tree_processes(),
    items: rows.map((row) =>
      row.kind === 'header'
        ? { id: `h-${row.category}`, disabled: true }
        : { id: row.process.process_id },
    ),
    onActivate: (index) => open(rows[index]),
    // windowing: the targeted row may not be rendered — so move the scroll instead
    scrollIntoView: (index) => {
      const scroller = scrollerRef.current;
      if (!scroller) return;
      const top = index * PROCESS_ROW_HEIGHT;
      const bottom = top + PROCESS_ROW_HEIGHT;
      if (top < scroller.scrollTop) scroller.scrollTop = top;
      else if (bottom > scroller.scrollTop + scroller.clientHeight) {
        scroller.scrollTop = bottom - scroller.clientHeight;
      }
    },
  });

  // The visible height follows the panel (splitters, window) — measured, never guessed.
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const observer = new ResizeObserver(() => setViewportHeight(scroller.clientHeight));
    observer.observe(scroller);
    return () => observer.disconnect();
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '4px 12px 8px' }}>
        <input
          value={query}
          placeholder={m.panels_search_process()}
          onInput={(e) => {
            setQuery((e.target as HTMLInputElement).value);
            setScrollTop(0);
            if (scrollerRef.current) scrollerRef.current.scrollTop = 0;
          }}
          style={{
            width: '100%',
            background: 'var(--vscode-input-background)',
            color: 'var(--vscode-input-foreground)',
            border: '1px solid var(--vscode-input-border)',
            borderRadius: '2px',
            padding: '3px 6px',
            font: '12px var(--retina-font-ui)',
            outline: 'none',
          }}
        />
      </div>
      <div
        ref={scrollerRef}
        {...nav.containerProps}
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', outline: 'none' }}
        onScroll={(e) => {
          cancelHover(); // the rows recycle under the cursor
          setScrollTop((e.target as HTMLDivElement).scrollTop);
        }}
      >
        <div style={{ height: `${start * PROCESS_ROW_HEIGHT}px` }} />
        {rows.slice(start, end).map((row, offset) => {
          const index = start + offset;
          if (row.kind === 'header') {
            return (
              <div
                key={`h-${row.category}`}
                class="tree-group"
                {...nav.itemProps(index)}
                style={{ height: `${PROCESS_ROW_HEIGHT}px`, padding: '4px 12px 0' }}
              >
                {row.category} <span class="dim">({row.count})</span>
              </div>
            );
          }
          const process = row.process;
          return (
            <button
              key={process.process_id}
              class="tree-row"
              {...nav.itemProps(index)}
              style={{ height: `${PROCESS_ROW_HEIGHT}px` }}
              onMouseEnter={(event) => scheduleHover(process, event as MouseEvent)}
              onMouseLeave={cancelHover}
              onClick={() => {
                nav.setActiveIndex(index);
                open(row);
              }}
            >
              <TablerIcon name={process.icon} />
              <span>{process.process_id}</span>
              {process.is_global && <span class="dim">{m.panels_global()}</span>}
            </button>
          );
        })}
        <div style={{ height: `${Math.max(0, rows.length - end) * PROCESS_ROW_HEIGHT}px` }} />
      </div>
      {hover && <HoverCard process={hover.process} x={hover.x} y={hover.y} />}
    </div>
  );
}

// --- Windows -----------------------------------------------------------------
/**
 * Context actions of a preview.
 *
 * `delete_preview`, `rename_preview` and `store_preview` had been served by the server and
 * echoed by the domain since day one, with no path at all in the interface: a preview could be
 * created with the mouse, but neither renamed nor deleted other than from the console. Nothing
 * new is added here — only a door.
 */
export function previewMenuItems(preview: ViewState): ContextMenuNode[] {
  return [
    {
      label: m.panels_go_to_view(),
      icon: 'eye',
      run: () => call('app.select_view', { view: preview.id }),
    },
    {
      label: m.panels_rename_menu(),
      icon: 'edit',
      run: () => {
        void promptText(m.panels_rename_preview(), preview.id, m.panels_rename()).then((name) => {
          // The domain refuses an empty or already-taken id: we do not duplicate its
          // validation, we let it say no — it is the one that knows the existing ids.
          if (name && name !== preview.id) {
            call('app.rename_preview', { old_id: preview.id, new_id: name });
          }
        });
      },
    },
    {
      label: m.panels_freeze_preview(),
      icon: 'lock',
      // An already-stored preview has nothing to store; the entry stays visible but inert, so
      // that the state reads the same in the menu as in the tree.
      disabled: preview.volatile === false,
      run: () => call('app.store_preview', { preview_id: preview.id }),
    },
    'separator',
    {
      label: m.prompt_delete(),
      icon: 'trash',
      danger: true,
      run: () => call('app.delete_preview', { preview_id: preview.id }),
    },
  ];
}

/** Context actions of an image window. */
export function windowMenuItems(win: WindowState): ContextMenuNode[] {
  return [
    {
      label: m.panels_activate(),
      icon: 'eye',
      run: () => call('app.select_view', { view: win.id }),
    },
    {
      label: m.panels_save_as(),
      icon: 'save',
      run: () => {
        // The main view, not the active one: `app.save` writes the window's main view, and
        // the 8-bit warning must judge the STF of what is actually going to be written.
        const main = win.views.find((view) => !view.is_preview);
        void saveImageAs(main, win.id, m.panels_save_window({ window: win.id })).catch(
          () => undefined,
        );
      },
    },
    'separator',
    {
      label: m.prompt_close(),
      icon: 'close',
      danger: true,
      run: () => call('app.close_window', { window: win.id }),
    },
  ];
}

function WindowsPanel() {
  const active = activeView.value;
  const list = windows.value;

  // Flattened for keyboard navigation: windows at level 1, previews at level 2 —
  // ←/→ climb up and down the hierarchy, ↑/↓ walk through it.
  const flat = list.flatMap((win) => [
    { kind: 'window' as const, win },
    ...win.views
      .filter((view) => view.is_preview)
      .map((preview) => ({ kind: 'preview' as const, win, preview })),
  ]);

  const nav = useTreeNav({
    idPrefix: 'windows-tree',
    label: m.panel_tree_windows(),
    items: flat.map((entry) =>
      entry.kind === 'window'
        ? { id: entry.win.id, level: 1 }
        : { id: entry.preview.id, level: 2 },
    ),
    onActivate: (index) => {
      const entry = flat[index];
      if (entry) {
        call('app.select_view', { view: entry.kind === 'window' ? entry.win.id : entry.preview.id });
      }
    },
  });

  if (list.length === 0) return <Empty text={m.panels_no_image_open()} />;

  return (
    <div {...nav.containerProps} style={{ outline: 'none' }}>
      {flat.map((entry, index) =>
        entry.kind === 'window' ? (
          <button
            key={entry.win.id}
            class="tree-row"
            {...nav.itemProps(index)}
            aria-selected={active?.id === entry.win.id}
            title={m.panels_window_menu_tip()}
            onClick={() => {
              nav.setActiveIndex(index);
              call('app.select_view', { view: entry.win.id });
            }}
            onContextMenu={(event) => openContextMenu(event, windowMenuItems(entry.win))}
          >
            <i class="codicon codicon-file-media" aria-hidden="true" />
            <span>{entry.win.id}</span>
            <span class="dim">
              {entry.win.width}×{entry.win.height}
            </span>
            {entry.win.is_modified && <span class="dim">●</span>}
          </button>
        ) : (
          <button
            key={entry.preview.id}
            class="tree-row"
            {...nav.itemProps(index)}
            style={{ paddingLeft: '28px' }}
            aria-selected={active?.id === entry.preview.id}
            title={m.panels_preview_menu_tip()}
            onClick={() => {
              nav.setActiveIndex(index);
              call('app.select_view', { view: entry.preview.id });
            }}
            onContextMenu={(event) => openContextMenu(event, previewMenuItems(entry.preview))}
          >
            {/* ⚡ volatile / 🔒 stored — same visual code as the old Qt panel */}
            <span>{entry.preview.volatile ? '⚡' : '🔒'}</span>
            <span>{entry.preview.id}</span>
          </button>
        ),
      )}
    </div>
  );
}

// --- History -----------------------------------------------------------------

/** Editing a past step: the process form, pre-filled, and "Replay".
 *
 * The non-destructive prototype plays out here, on the client side, in about thirty lines:
 * the schema comes from the process catalogue, the values from the history entry, and the
 * replay is an RPC call. None of it is specific to the shell — `app.replay_history` is also
 * available from the console, and it is the same function that does the work.
 */
function HistoryStepEditor({ index, processId, onDone }: {
  index: number;
  processId: string;
  onDone: () => void;
}) {
  const meta = processCatalog.value.find((p) => p.process_id === processId);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [erreur, setErreur] = useState('');

  // The step's values are not in the snapshot (it only carries the `process_id`s): we ask the
  // recipe for them, since it is already the replayable projection of the history.
  useEffect(() => {
    void client
      .call<RecipeStep[]>('app.recipe')
      .then((steps) => setValues({ ...(steps[index - 1]?.values ?? {}) }))
      .catch((error: unknown) => console.error(error));
  }, [index, processId]);

  if (!meta) return null;
  return (
    <div style={{ padding: '6px 8px', display: 'grid', gap: '6px' }}>
      <ParameterGrid
        parameters={meta.parameters}
        values={values}
        onChange={(next) => setValues(next)}
      />
      {erreur && <span style={{ color: 'var(--vscode-errorForeground)' }}>{erreur}</span>}
      <div style={{ display: 'flex', gap: '6px' }}>
        <button
          class="btn"
          onClick={() => {
            setErreur('');
            void client
              .call('app.replay_history', { index, values })
              .then(onDone)
              .catch((error: unknown) => setErreur(String(error)));
          }}
        >
          {m.panels_replay()}
        </button>
        <button class="btn" onClick={onDone}>
          {m.panels_replay_cancel()}
        </button>
      </div>
    </div>
  );
}

function HistoryPanel() {
  const view = activeView.value;
  const [edite, setEdite] = useState<number | null>(null);
  if (!view) return <Empty text={m.panels_no_active_view()} />;
  const { labels, index, processes: stepProcesses } = view.history;

  return (
    <div>
      {/* The history-explorer gesture: a view's history *is* a recipe, and must be able to
          become an object one keeps, reorders and replays. */}
      <button
        class="btn"
        disabled={index === 0}
        title={m.panels_recipe_tip()}
        style={{ margin: '6px 8px' }}
        onClick={() => {
          void client
            .call<RecipeStep[]>('app.recipe')
            .then((steps) => setSteps(newContainer(), steps))
            .catch((error: unknown) => console.error(error));
        }}
      >
        <i class="codicon codicon-list-ordered" aria-hidden="true" />{' '}
        {m.panels_recipe_from_history()}
      </button>
      {labels.map((label, i) => {
        const processId = stepProcesses?.[i] ?? null;
        return (
          <div key={`${i}-${label}`}>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <button
                class="tree-row"
                aria-selected={i === index}
                style={{ opacity: i > index ? 0.5 : 1, flex: 1 }}
                title={i > index ? m.panels_redoable_state() : ''}
                onClick={() => call('app.go_to_history', { index: i })}
              >
                <i
                  class={`codicon codicon-${i === 0 ? 'circle-outline' : 'circle-filled'}`}
                  aria-hidden="true"
                />
                <span>{label}</span>
              </button>
              {/* The pencil only appears on a genuinely replayable step: the initial state
                  and a process absent from this installation have none. */}
              {processId && (
                <button
                  class="btn"
                  title={m.panels_replay_tip()}
                  aria-label={m.panels_replay_tip()}
                  onClick={() => setEdite(edite === i ? null : i)}
                >
                  <i class="codicon codicon-edit" aria-hidden="true" />
                </button>
              )}
            </div>
            {edite === i && processId && (
              <HistoryStepEditor
                index={i}
                processId={processId}
                onDone={() => setEdite(null)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// --- utilities ---------------------------------------------------------------
function Empty({ text }: { text: string }) {
  return (
    <p
      style={{
        color: 'var(--vscode-descriptionForeground)',
        fontSize: '12px',
        padding: '8px 12px',
        margin: 0,
      }}
    >
      {text}
    </p>
  );
}

/** Rendering a panel by its id. The only place that knows the mapping. */
export function PanelContent({ panel }: { panel: PanelId }) {
  switch (panel) {
    case 'explorer':
      return <ProcessExplorer />;
    case 'files':
      return <FilesPanel />;
    case 'windows':
      return <WindowsPanel />;
    case 'history':
      return <HistoryPanel />;
    case 'stf':
      return <StfPanel />;
    case 'console':
      return <ConsolePanel />;
    case 'chat':
      return <ChatPanel />;
    case 'library':
      return <LibraryPanel />;
    case 'header':
      return <HeaderPanel />;
    case 'rtp':
      // The preview lives as a split of the active viewport (cf. CenterDock): comparing
      // before/after means seeing them side by side, not in a bottom dock.
      return <Empty text={m.panels_rtp_hint()} />;
    case 'doc':
      // Rendered as a centre tab (cf. CenterDock) — long reading deserves the width.
      return <Empty text={m.panels_doc_hint()} />;
    case 'desktop':
      return <Empty text={m.panels_desktop_hint()} />;
    case 'pipeline':
      // A centre tab as well: the walkthrough has a table, a plan and a log.
      return <Empty text={m.panels_pipeline_hint()} />;
    case 'settings':
      // A centre tab: a wide read, and nothing to do with the active image.
      return <Empty text={m.panels_settings_hint()} />;
    case 'credits':
      return <Empty text={m.panels_credits_hint()} />;
    default:
      return <Empty text={m.panels_generic({ panel })} />;
  }
}
