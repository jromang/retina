// Toast stack — the ephemeral announcement, of which the notification center is the memory.
//
// Bottom right, above the status bar: the area the eye already consults for the state of the
// application. `aria-live="polite"` has a screen reader announce arrivals without interrupting;
// errors stay until acted upon, the rest fade by themselves.

import { m } from '../paraglide/messages';
import { dismissToast, toasts, type NotificationKind } from './store';

const ICONS: Record<NotificationKind, string> = {
  info: 'info',
  warning: 'warning',
  error: 'error',
};

const COLORS: Record<NotificationKind, string> = {
  info: 'var(--vscode-charts-blue, #3794ff)',
  warning: 'var(--vscode-charts-yellow, #cca700)',
  error: 'var(--vscode-errorForeground, #f48771)',
};

export function Toasts() {
  if (toasts.value.length === 0) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed',
        right: '12px',
        bottom: '34px',
        zIndex: 60,
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        maxWidth: '360px',
      }}
    >
      {toasts.value.map((toast) => (
        <div
          key={toast.key}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: '8px',
            padding: '8px 10px',
            background: 'var(--vscode-editorWidget-background, #252526)',
            border: '1px solid var(--vscode-editorWidget-border, #454545)',
            borderLeft: `3px solid ${COLORS[toast.kind]}`,
            borderRadius: '3px',
            fontSize: '12px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.35)',
          }}
        >
          <i
            class={`codicon codicon-${ICONS[toast.kind]}`}
            style={{ color: COLORS[toast.kind], marginTop: '1px' }}
            aria-hidden="true"
          />
          <span style={{ flex: 1, overflowWrap: 'anywhere' }}>
            {toast.source && <strong style={{ marginRight: '4px' }}>{toast.source}</strong>}
            {toast.message}
            {toast.action && (
              <button
                class="btn"
                style={{ display: 'block', marginTop: '6px' }}
                onClick={() => {
                  toast.action?.run();
                  dismissToast(toast.key);
                }}
              >
                {toast.action.label}
              </button>
            )}
          </span>
          <button
            title={m.notif_toast_close()}
            aria-label={m.notif_toast_close()}
            onClick={() => dismissToast(toast.key)}
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
  );
}
