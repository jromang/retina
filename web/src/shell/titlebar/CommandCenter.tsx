// Command center — the clickable bar at the center of the title bar.
//
// In VS Code it displays the current file and opens quick open. Here it displays the active
// view (that is the equivalent of the open "document") and opens the palette, which already
// contains the commands, the 115 processes and the windows.

import { m } from '../../paraglide/messages';
import { currentProject, hasUnsavedWork, projectName } from '../../project/project';
import { activeView, activeWindow } from '../../state/store';
import { openPalette } from '../uiState';

export function CommandCenter() {
  const win = activeWindow.value;
  const view = activeView.value;
  // The label follows the view, not the window: on a preview, it is the preview that gets processed.
  const label = view && win && view.id !== win.id ? `${win.id} › ${view.id}` : (win?.id ?? null);
  const project = currentProject.value;
  // Pure display, not a domain action: we name the project and flag unsaved
  // work, the way VS Code marks a modified tab.
  const dirty = hasUnsavedWork();

  return (
    <button
      type="button"
      class="command-center"
      onClick={openPalette}
      title={project ? m.palette_project({ path: project }) : m.status_palette()}
    >
      <i class="codicon codicon-search" aria-hidden="true" />
      <span class="command-center-label" data-empty={label === null}>
        {label ?? m.palette_center_placeholder()}
      </span>
      {project && (
        <span class="command-center-project">
          {projectName(project)}
          {dirty ? ' ●' : ''}
        </span>
      )}
    </button>
  );
}
