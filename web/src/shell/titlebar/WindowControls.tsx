// Minimize / maximize / close buttons.
//
// Mounted only in the native window: in browser mode, it is the browser that carries
// this chrome and these buttons could do nothing.

import { m } from '../../paraglide/messages';
import { hasUnsavedWork } from '../../project/project';
import { confirmBox } from '../../ui/prompts';
import { windowClose, windowMaximized, windowMinimize, windowToggleMaximize } from './windowClient';

/**
 * Closing the native window — with the same guard as a page reload.
 *
 * `beforeunload` does **not** protect this button: it goes out as direct IPC to the shell, without
 * going through the document's navigation. Without this confirmation, the most definitive gesture
 * in the application would be the only one to ask nothing.
 */
function closeWindow(): void {
  if (!hasUnsavedWork()) {
    windowClose();
    return;
  }
  void confirmBox(m.window_unsaved_quit(), m.window_quit()).then(
    (confirmed) => {
      if (confirmed) windowClose();
    },
  );
}

export function WindowControls() {
  const maximized = windowMaximized.value;

  return (
    <div class="window-controls">
      <button type="button" class="window-control" title={m.window_minimize()} onClick={windowMinimize}>
        <i class="codicon codicon-chrome-minimize" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="window-control"
        title={maximized ? m.window_restore() : m.window_maximize()}
        onClick={windowToggleMaximize}
      >
        <i
          class={`codicon codicon-chrome-${maximized ? 'restore' : 'maximize'}`}
          aria-hidden="true"
        />
      </button>
      <button type="button" class="window-control close" title={m.prompt_close()} onClick={closeWindow}>
        <i class="codicon codicon-chrome-close" aria-hidden="true" />
      </button>
    </div>
  );
}
