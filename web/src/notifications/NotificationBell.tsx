// Status bar bell + notification center as a popover.
//
// Same pattern as `ReadoutOptions`: a popover anchored to its button, no menu infrastructure
// for three gestures. The content is the mirror of the domain center — dismiss and "clear all"
// go through RPC, hence through `app.notifications.*`, hence with an echo.

import { m } from '../paraglide/messages';
import {
  centerOpen,
  clearAll,
  dismiss,
  errorCount,
  notifications,
  type NotificationKind,
} from './store';

const COLORS: Record<NotificationKind, string> = {
  info: 'var(--vscode-charts-blue, #3794ff)',
  warning: 'var(--vscode-charts-yellow, #cca700)',
  error: 'var(--vscode-errorForeground, #f48771)',
};

function timeOf(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function NotificationBell() {
  const list = notifications.value;
  const open = centerOpen.value;

  return (
    <span style={{ position: 'relative' }}>
      <button
        class="status-item"
        title={m.status_notifications()}
        aria-expanded={open}
        onClick={() => (centerOpen.value = !open)}
      >
        <i
          class={`codicon codicon-${errorCount.value > 0 ? 'bell-dot' : 'bell'}`}
          aria-hidden="true"
        />
        {list.length > 0 && <span style={{ marginLeft: '4px' }}>{list.length}</span>}
      </button>
      {open && (
        <div
          class="popover"
          style={{
            position: 'absolute',
            bottom: '100%',
            right: 0,
            zIndex: 50,
            width: '340px',
            maxHeight: '50vh',
            overflowY: 'auto',
            padding: '6px',
            display: 'grid',
            gap: '4px',
            background: 'var(--vscode-menu-background, #252526)',
            border: '1px solid var(--vscode-menu-border, #454545)',
            borderRadius: '3px',
            fontSize: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', padding: '2px 4px' }}>
            <strong style={{ flex: 1 }}>{m.notif_title()}</strong>
            {list.length > 0 && (
              <button
                onClick={clearAll}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--vscode-textLink-foreground, #3794ff)',
                  cursor: 'pointer',
                  fontSize: '11px',
                }}
              >
                {m.notif_clear_all()}
              </button>
            )}
          </div>
          {list.length === 0 && (
            <span style={{ padding: '6px 4px', opacity: 0.7 }}>{m.notif_empty()}</span>
          )}
          {list.map((note) => (
            <div
              key={note.id}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '6px',
                padding: '4px',
                borderLeft: `2px solid ${COLORS[note.kind]}`,
              }}
            >
              <span style={{ flex: 1, overflowWrap: 'anywhere' }}>
                {note.source && <strong style={{ marginRight: '4px' }}>{note.source}</strong>}
                {note.message}
                <span style={{ opacity: 0.6, marginLeft: '6px' }}>{timeOf(note.timestamp)}</span>
              </span>
              <button
                title={m.notif_dismiss()}
                aria-label={m.notif_dismiss()}
                onClick={() => dismiss(note.id)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'inherit',
                  cursor: 'pointer',
                  padding: 0,
                }}
              >
                <i class="codicon codicon-close" aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
      )}
    </span>
  );
}
