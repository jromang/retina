// The shell: fixed CSS grid, zones, resize handles, global shortcuts.
//
// The visibility of the zones comes from `panelVisible`, which is driven by the server. An
// `app.layout.show('history')` typed in the console therefore travels the whole path — domain →
// Python mirror → notification → signal → CSS grid — and the panel appears. That is the proof
// that the shell has no power of its own.

import { m } from '../paraglide/messages';
import { useEffect, useRef, useState } from 'preact/hooks';

import { CenterDock } from '../center/CenterDock';
import { PanelContent } from '../panels';
import { ProcessPanel } from '../processes/ProcessPanel';
import { releaseRtp } from '../processes/rtp';
import { hasUnsavedWork } from '../project/project';
import { Toasts } from '../notifications/Toasts';
import { processes } from '../state/store';
import { TablerIcon } from './TablerIcon';
import type { ViewportStatus } from '../viewport/ViewportPanel';
import { ActivityBar } from './ActivityBar';
import { CommandPalette } from './CommandPalette';
import { commandIndex } from './commands';
import { buildKeymap, eventChord, firesWhileTyping, isTyping } from './keybindings';
import { ContextMenuHost } from '../ui/ContextMenu';
import { PromptHost } from '../ui/PromptHost';
import { Tour } from './Tour';
import { ShortcutsSheet } from './ShortcutsSheet';
import { StatusBar } from './StatusBar';
import { closePalette, paletteOpen } from './uiState';
import { setZoneSize, zoneSizes } from './zoneSizes';
import { TitleBar } from './titlebar/TitleBar';
import { WindowResizeHandles } from './WindowResizeHandles';
import { inNativeShell } from './native';
import {
  activeSidebarPanel,
  layoutLocked,
  openProcesses,
  panelVisible,
  reportLayout,
  requestCloseProcess,
  requestToggle,
} from './layoutClient';
import { BOTTOM_PANELS, PANEL_META, RIGHT_PANELS, type PanelId } from './panels';
import '../styles/workbench.css';

const MIN_SIDEBAR = 170;
const MAX_SIDEBAR = 640;
const MIN_BOTTOM = 80;
const MAX_BOTTOM = 640;

/** Resize handle. Neutralized when the layout is locked. */
function Splitter({
  orientation,
  style,
  onDrag,
}: {
  orientation: 'v' | 'h';
  style: Record<string, string>;
  onDrag: (delta: number) => void;
}) {
  const [dragging, setDragging] = useState(false);

  const onPointerDown = (event: PointerEvent) => {
    if (layoutLocked.value) return;
    event.preventDefault();
    setDragging(true);
    const start = orientation === 'v' ? event.clientX : event.clientY;
    let last = start;
    const move = (e: PointerEvent) => {
      const current = orientation === 'v' ? e.clientX : e.clientY;
      onDrag(current - last);
      last = current;
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  return (
    <div
      class={`splitter splitter-${orientation}`}
      data-dragging={dragging}
      style={style}
      onPointerDown={onPointerDown}
    />
  );
}

function SidebarZone({ panel }: { panel: PanelId }) {
  return (
    <aside class="sidebar">
      <header class="panel-title">
        <span>{PANEL_META[panel].title}</span>
      </header>
      <div class="panel-body">
        <PanelContent panel={panel} />
      </div>
    </aside>
  );
}

/**
 * Right zone: the process tool windows, then the fixed panels (STF).
 *
 * The reference model is kept — an open process is a singleton window one keeps at
 * hand while adjusting. They are stacked above the STF, like the "process
 * area" above the same group.
 */
/** Icon of a tool window's process — the dock only knows its id. */
function ProcessTitleIcon({ processId }: { processId: string }) {
  const meta = processes.value.find((p) => p.process_id === processId);
  return meta ? <TablerIcon name={meta.icon} /> : null;
}

function RightZone({ panels }: { panels: readonly PanelId[] }) {
  const open = openProcesses.value;
  return (
    <aside class="right-dock">
      {open.map((processId) => (
        <div
          key={processId}
          style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: '160px' }}
        >
          <header class="panel-title">
            <ProcessTitleIcon processId={processId} />
            <span>{processId}</span>
            <span style={{ flex: 1 }} />
            {/* The closing ✕ existed, but buried in the bottom action bar, next to
                "Apply" — invisible as a closing gesture. We move it up into the
                header, like the normal panels (same releaseRtp as the bottom close). */}
            <button
              class="activity-item"
              style={{ width: '22px', height: '22px', fontSize: '14px' }}
              title={m.prompt_close()}
              onClick={() => {
                releaseRtp(processId);
                requestCloseProcess(processId);
              }}
            >
              <i class="codicon codicon-close" aria-hidden="true" />
            </button>
          </header>
          <div style={{ flex: 1, overflow: 'hidden' }}>
            <ProcessPanel
              processId={processId}
              onClose={() => requestCloseProcess(processId)}
            />
          </div>
        </div>
      ))}
      {panels.map((panel) => (
        // `minHeight: 0`: without it, `min-height: auto` keeps this flex wrapper from
        // shrinking below the size of its content, it overflows the column (which `.right-dock`
        // clips) and the bottom of a panel — the Assistant's composer — slides under the
        // bottom panel. With it, `.panel-body` (overflow:auto) scrolls and the composer fits.
        <div key={panel} style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
          <header class="panel-title">
            <span>{PANEL_META[panel].title}</span>
            <span style={{ flex: 1 }} />
            <button
              class="activity-item"
              style={{ width: '22px', height: '22px', fontSize: '14px' }}
              title={m.workbench_close_panel()}
              onClick={() => requestToggle(panel)}
            >
              <i class="codicon codicon-close" aria-hidden="true" />
            </button>
          </header>
          <div class="panel-body">
            <PanelContent panel={panel} />
          </div>
        </div>
      ))}
    </aside>
  );
}

function BottomZone({ panels }: { panels: readonly PanelId[] }) {
  const [selected, setSelected] = useState<PanelId>(panels[0] ?? 'console');
  const active = panels.includes(selected) ? selected : (panels[0] ?? 'console');

  return (
    <section class="bottom">
      <div class="bottom-tabs">
        {panels.map((panel) => (
          <button
            key={panel}
            class="bottom-tab"
            aria-selected={panel === active}
            onClick={() => setSelected(panel)}
          >
            {PANEL_META[panel].title}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <button
          class="bottom-tab"
          title={m.workbench_hide_bottom()}
          onClick={() => requestToggle(active)}
        >
          <i class="codicon codicon-chevron-down" aria-hidden="true" />
        </button>
      </div>
      <div class="panel-body">
        <PanelContent panel={active} />
      </div>
    </section>
  );
}

export function Workbench() {
  const [status, setStatus] = useState<ViewportStatus | null>(null);
  // A module signal and not `useState`: a perspective or a project must be able to
  // set them again while this component is already mounted (see `shell/zoneSizes.ts`).
  const { sidebar: sidebarWidth, right: rightWidth, bottom: bottomHeight } = zoneSizes.value;
  const rootRef = useRef<HTMLDivElement>(null);
  // Stable for the duration of the session: the shell's INIT_SCRIPT runs before any
  // page script, so the marker is already there at the first render.
  const native = inNativeShell();

  const sidebar = activeSidebarPanel.value;
  const rightPanels = RIGHT_PANELS.filter((panel) => panelVisible.value[panel]);
  const bottomPanels = BOTTOM_PANELS.filter((panel) => panelVisible.value[panel]);

  // Global shortcuts — **derived** from the command registry, nothing hard-coded here any more. A
  // key advertised by the palette is therefore wired by construction, and the converse too: the
  // viewport keys (+, −, 1, F) had no handler at all until now even though the
  // palette displayed them.
  //
  // The `typing` guard is what makes the bare keys safe: in a field, one types, one does not
  // drive. Only the interface's escape hatches (palette, documentation) are exceptions to it.
  // It covers the Monaco editor **through its root** and not only through its hidden
  // textarea: the click that gives focus takes a moment to reach it, and a `b` typed
  // in that interval went off to trigger the A/B toggle instead of being written — the first
  // character of a fast keystroke disappeared.
  useEffect(() => {
    // User layouts never carry a shortcut: no need to load them
    // here, and it avoids a network round trip at mount time.
    const index = commandIndex([], processes.value);
    const keymap = buildKeymap(index.values());
    const onKey = (event: KeyboardEvent) => {
      const chord = eventChord(event);
      if (!chord) return;
      const command = index.get(keymap.get(chord) ?? '');
      if (!command) return;
      if (isTyping(event.target) && !firesWhileTyping(chord)) return;

      event.preventDefault(); // F5 would reload the page, Ctrl+O would open the browser's picker
      command.run();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [processes.value]);

  // The size of the zones is a local preference, not domain state: we only report the
  // visibility to the server, which is what `app.layout.is_visible` has to know.
  useEffect(() => {
    reportLayout();
  }, [panelVisible.value]);

  // A page reload used to lose everything without asking, whereas closing a single script
  // tab asked for confirmation: the most destructive gesture was the least protected.
  // The browser imposes its own wording — all we can do is trigger the request.
  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedWork()) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, []);

  return (
    <div
      ref={rootRef}
      class="workbench"
      data-sidebar={sidebar ? 'shown' : 'hidden'}
      data-right={rightPanels.length > 0 ? 'shown' : 'hidden'}
      data-bottom={bottomPanels.length > 0 ? 'shown' : 'hidden'}
      style={{
        '--sidebar-width': `${sidebarWidth}px`,
        '--right-width': `${rightWidth}px`,
        '--bottom-height': `${bottomHeight}px`,
      }}
    >
      <TitleBar native={native} />
      <ActivityBar />
      {sidebar && <SidebarZone panel={sidebar} />}
      <div class="center">
        <CenterDock onStatus={setStatus} />
        {sidebar && (
          <Splitter
            orientation="v"
            style={{ left: '-2px' }}
            // `d` is incremental: read the LIVE size from the signal, not `sidebarWidth` frozen at
            // the start of the gesture — the `move` closure keeps the `onDrag` of the pointer-down,
            // so a captured value would never accumulate and the panel would snap back to its size.
            onDrag={(d) =>
              setZoneSize(
                'sidebar',
                Math.min(MAX_SIDEBAR, Math.max(MIN_SIDEBAR, zoneSizes.value.sidebar + d)),
              )
            }
          />
        )}
        {rightPanels.length > 0 && (
          <Splitter
            orientation="v"
            style={{ right: '-2px' }}
            onDrag={(d) =>
              setZoneSize(
                'right',
                Math.min(MAX_SIDEBAR, Math.max(MIN_SIDEBAR, zoneSizes.value.right - d)),
              )
            }
          />
        )}
        {bottomPanels.length > 0 && (
          <Splitter
            orientation="h"
            style={{ bottom: '-2px' }}
            onDrag={(d) =>
              setZoneSize(
                'bottom',
                Math.min(MAX_BOTTOM, Math.max(MIN_BOTTOM, zoneSizes.value.bottom - d)),
              )
            }
          />
        )}
      </div>
      {rightPanels.length > 0 && <RightZone panels={rightPanels} />}
      {bottomPanels.length > 0 && <BottomZone panels={bottomPanels} />}
      <StatusBar status={status} />
      <Toasts />
      <WindowResizeHandles />
      {paletteOpen.value && <CommandPalette onClose={closePalette} />}
      <ShortcutsSheet />
      <PromptHost />
      <ContextMenuHost />
      <Tour />
    </div>
  );
}
