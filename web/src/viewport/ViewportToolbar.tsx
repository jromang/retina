// Viewport toolbar and breadcrumb of the view.
//
// Discipline taken from ``gui/viewport_toolbar.py``: **no handler contains any logic**,
// each one calls an RPC that goes through ``app.*`` and produces its echo. Changing the
// interaction mode writes `app.set_interaction_mode(retina.InteractionMode.PAN)` into the console.
//
// The breadcrumb is an addition compared to the former Qt shell: it shows `image › preview` and
// allows switching views without taking one's eyes off the viewport. The Windows panel remains
// the inventory; the breadcrumb becomes the everyday selector.

import { useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import { previewMenuItems } from '../panels';
import { openContextMenu } from '../ui/ContextMenu';
import { dynamicTool } from './dynamicTool';
import type { ViewState, WindowState } from '../api/types';
import { snapshot } from '../state/store';

const MODES: Array<{ id: string; icon: string; label: string }> = [
  { id: 'readout', icon: 'target', label: m.viewport_mode_readout() },
  { id: 'pan', icon: 'move', label: m.viewport_mode_pan() },
  { id: 'zoom_in', icon: 'zoom-in', label: m.viewport_mode_zoom_in() },
  { id: 'zoom_out', icon: 'zoom-out', label: m.viewport_mode_zoom_out() },
  { id: 'center', icon: 'circle-large-outline', label: m.viewport_mode_center() },
  { id: 'new_preview', icon: 'screen-normal', label: m.viewport_mode_new_preview() },
  { id: 'edit_preview', icon: 'edit', label: m.viewport_mode_edit_preview() },
];

function call(method: string, params?: Record<string, unknown>): void {
  void client.call(method, params).catch((error: unknown) => console.error(method, error));
}

/**
 * What a click will do when a dynamic tool is armed.
 *
 * Without this indicator, `dynamic` is the only mode in which the toolbar icon says
 * nothing: the seven other modes light up, this one has no button — it is a panel that
 * armed it. So we give its name, and the way out (Esc does the same thing).
 */
function ActiveToolBadge() {
  const tool = dynamicTool.value;
  if (!tool) return null;
  return (
    <span
      class="status-item"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
        marginLeft: '8px',
        padding: '1px 6px',
        borderRadius: '9px',
        fontSize: '11px',
        background: 'var(--vscode-list-activeSelectionBackground)',
      }}
    >
      <i class="codicon codicon-tools" aria-hidden="true" />
      {tool.label}
      <button
        style={{ ...buttonStyle, fontSize: '11px', padding: '0 2px' }}
        title={m.viewport_exit_tool()}
        onClick={() => call('app.set_interaction_mode', { mode: 'readout' })}
      >
        <i class="codicon codicon-close" aria-hidden="true" />
      </button>
    </span>
  );
}

const buttonStyle = {
  background: 'none',
  border: 'none',
  color: 'var(--vscode-foreground)',
  cursor: 'pointer',
  padding: '2px 5px',
  fontSize: '15px',
  borderRadius: '2px',
} as const;

/**
 * Toggle for pan/zoom synchronization between windows.
 *
 * The state comes from the snapshot, not from a local signal: `app.link_viewports()` typed in
 * the console must light the button up, and two connected clients must see the same thing.
 */
function LinkToggle({ window: win }: { window: WindowState }) {
  const linked = snapshot.value?.linked_viewports ?? [];
  const active = linked.includes(win.id);
  return (
    <button
      style={{
        ...buttonStyle,
        background: active ? 'var(--vscode-list-activeSelectionBackground)' : 'none',
      }}
      title={
        active
          ? m.viewport_linked({ count: linked.length })
          : m.viewport_link_hint()
      }
      onClick={() => call(active ? 'app.unlink_viewports' : 'app.link_viewports')}
    >
      <i class={`codicon codicon-${active ? 'link' : 'link-external'}`} aria-hidden="true" />
    </button>
  );
}

export function ViewportToolbar({ window: win }: { window: WindowState }) {
  const mode = win.viewport.interaction_mode;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '2px',
        padding: '2px 6px',
        borderBottom: '1px solid var(--vscode-panel-border)',
        background: 'var(--vscode-editorWidget-background)',
      }}
    >
      <button style={buttonStyle} title={m.viewport_zoom_out()} onClick={() => call('app.zoom_out')}>
        <i class="codicon codicon-remove" aria-hidden="true" />
      </button>
      <button style={buttonStyle} title={m.viewport_zoom_in()} onClick={() => call('app.zoom_in')}>
        <i class="codicon codicon-add" aria-hidden="true" />
      </button>
      <button
        style={{ ...buttonStyle, fontSize: '11px' }}
        title={m.viewport_zoom_11()}
        onClick={() => call('app.zoom_1_1')}
      >
        1:1
      </button>
      <button
        style={{ ...buttonStyle, fontSize: '11px' }}
        title={m.viewport_zoom_fit()}
        onClick={() => call('app.zoom_to_fit')}
      >
        {m.viewport_fit()}
      </button>

      <span style={{ width: '8px' }} />

      {MODES.map((entry) => (
        <button
          key={entry.id}
          style={{
            ...buttonStyle,
            background: mode === entry.id ? 'var(--vscode-list-activeSelectionBackground)' : 'none',
          }}
          title={entry.label}
          onClick={() => call('app.set_interaction_mode', { mode: entry.id })}
        >
          <i class={`codicon codicon-${entry.icon}`} aria-hidden="true" />
        </button>
      ))}

      <ActiveToolBadge />

      <span style={{ flex: 1 }} />

      <LinkToggle window={win} />

      <button
        style={{ ...buttonStyle, fontSize: '11px' }}
        title={m.viewport_autostretch_tip()}
        onClick={() => call('app.compute_auto_stf')}
      >
        Auto STF
      </button>
    </div>
  );
}

/** Breadcrumb: `image › view`, with a preview selector. */
export function Breadcrumb({
  window: win,
  view,
}: {
  window: WindowState;
  view: ViewState;
}) {
  const [open, setOpen] = useState(false);
  const previews = win.views.filter((candidate) => candidate.is_preview);
  const name = win.file_path ? win.file_path.split(/[\\/]/).pop() : win.id;

  return (
    <div
      style={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
        padding: '2px 8px',
        fontSize: '12px',
        color: 'var(--vscode-descriptionForeground)',
        borderBottom: '1px solid var(--vscode-panel-border)',
      }}
    >
      <i class="codicon codicon-file-media" aria-hidden="true" />
      <span>{name}</span>
      <i class="codicon codicon-chevron-right" style={{ fontSize: '11px' }} aria-hidden="true" />
      <button
        onClick={() => setOpen(!open)}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--vscode-foreground)',
          cursor: previews.length ? 'pointer' : 'default',
          font: 'inherit',
          padding: 0,
          display: 'flex',
          alignItems: 'center',
          gap: '3px',
        }}
      >
        {view.is_preview ? (view.volatile ? '⚡' : '🔒') : ''} {view.id}
        {previews.length > 0 && (
          <i class="codicon codicon-chevron-down" style={{ fontSize: '11px' }} aria-hidden="true" />
        )}
      </button>

      {open && previews.length > 0 && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: '60px',
            zIndex: 10,
            background: 'var(--vscode-editorWidget-background)',
            border: '1px solid var(--vscode-editorWidget-border)',
            borderRadius: '3px',
            boxShadow: '0 4px 12px var(--vscode-widget-shadow)',
            minWidth: '160px',
          }}
          onMouseLeave={() => setOpen(false)}
        >
          {[win.views[0], ...previews].filter(Boolean).map((candidate) => (
            <button
              key={candidate!.id}
              class="tree-row"
              aria-selected={candidate!.id === view.id}
              title={candidate!.is_preview ? m.viewport_preview_menu_hint() : undefined}
              onClick={() => {
                setOpen(false);
                call('app.select_view', { view: candidate!.id });
              }}
              onContextMenu={(event) => {
                // The same menu as in the Windows panel: the breadcrumb is where
                // one is *currently* looking at one's previews, hence where one wants to manage them.
                if (!candidate!.is_preview) return;
                setOpen(false);
                openContextMenu(event, previewMenuItems(candidate!));
              }}
            >
              <span>
                {candidate!.is_preview ? (candidate!.volatile ? '⚡' : '🔒') : '🖼'}
              </span>
              <span>{candidate!.id}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
