// The current project on the client side — save, open, and answer the server.
//
// This module has **no power of its own**: each gesture calls `project.save` / `project.open`,
// which delegate to `app.save_project` / `app.open_project` and produce the Python echo. What
// belongs to it proper is the client side of the dialogue: serializing the documents when the
// server asks for them, restoring them when it hands them back.
//
// The pattern is copied from `layoutClient` (`pendingSave` → `layout.store_perspective`), with
// one correlation more: here the server *waits* for the answer in order to write its file.

import { batch, signal } from '@preact/signals';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import { startTourIfFirstRun } from '../shell/Tour';
import type { ProjectCommand, SessionState } from '../api/types';
import { openContainers } from '../pipeline/containerEdit';
import { openScripts } from '../scripts/scripts';
import { reconcileWithServer } from '../shell/locale';
import { PROJECT_FILTERS, askPath } from '../shell/native';
import { confirmBox } from '../ui/prompts';
import { restoreDocuments, serializeDocuments } from './documents';

/** Path of the current project, or `null` while the session has not been saved. */
export const currentProject = signal<string | null>(null);
export const recentFiles = signal<readonly string[]>([]);
export const recentProjects = signal<readonly string[]>([]);
/** True if the server has an implicit session to offer to reopen (home screen). */
export const hasAutosession = signal(false);

/** Pending document request — same pattern as the perspectives' `pendingSave`. */
const pendingRequest = signal<string | null>(null);

/**
 * A single restore from the `hello`.
 *
 * A reconnection (server restarted, WebSocket dropped) would otherwise replay the last
 * project's blob **on top of** the live state, and the user would lose what they typed since.
 */
let restoredFromHello = false;

export function projectName(path: string | null): string {
  if (!path) return '';
  const base = path.split(/[\\/]/).filter(Boolean).pop() ?? path;
  return base.replace(/\.retina$/i, '');
}

function directoryOf(path: string | null): string | undefined {
  if (!path) return undefined;
  const separator = path.includes('\\') && !path.includes('/') ? '\\' : '/';
  const cut = path.lastIndexOf(separator);
  return cut > 0 ? path.slice(0, cut) : undefined;
}

/** Is there unsaved work? — for `beforeunload` and the confirmations. */
export function hasUnsavedWork(): boolean {
  return (
    openScripts.value.some((doc) => doc.dirty) ||
    openContainers.value.some((doc) => doc.dirty)
  );
}

// --- gestures --------------------------------------------------------------

export async function saveProject(forcePath = false): Promise<void> {
  let path = currentProject.value;
  if (!path || forcePath) {
    const dossier = directoryOf(path);
    const chosen = await askPath({
      title: m.project_save_dialog(),
      save: true,
      filters: PROJECT_FILTERS,
      filename: path ? projectName(path) : m.project_default_filename(),
      ...(dossier ? { directory: dossier } : {}),
    });
    if (!chosen?.[0]) return;
    path = chosen[0];
  }
  await client.call('project.save', { path });
}

export async function openProject(path?: string): Promise<void> {
  let cible = path;
  if (!cible) {
    const dossier = directoryOf(currentProject.value);
    const chosen = await askPath({
      title: m.project_open_dialog(),
      filters: PROJECT_FILTERS,
      ...(dossier ? { directory: dossier } : {}),
    });
    if (!chosen?.[0]) return;
    cible = chosen[0];
  }
  // Opening a project replaces the whole session, documents included: ask first, as when
  // closing a modified script.
  if (hasUnsavedWork()) {
    const suite = await confirmBox(m.project_unsaved_open(), m.project_open_confirm());
    if (!suite) return;
  }
  await client.call('project.open', { path: cible });
}

export async function closeProject(): Promise<void> {
  if (hasUnsavedWork()) {
    const suite = await confirmBox(m.project_unsaved_close(), m.prompt_close());
    if (!suite) return;
  }
  await client.call('project.close');
}

export function setReopenSession(enabled: boolean): void {
  void client.call('project.set_reopen', { enabled }).catch((e: unknown) => console.error(e));
}

export async function refreshRecent(): Promise<void> {
  try {
    const state = await client.call<SessionState>('project.recent');
    // Changing the language is also a session change. It arrives here when it comes from the
    // console (`app.set_language`) or from another client: the interface reloads, the only way
    // to rebuild label tables frozen at their modules' import time.
    if (reconcileWithServer(state.effective_language)) return;
    adoptSession(state);
  } catch (error) {
    console.error(error);
  }
}

/** Changes the interface language. Goes through the domain — hence echoed, hence scriptable. */
export function setLanguage(language: string | null): void {
  void client
    .call('project.set_language', { language })
    .catch((e: unknown) => console.error(e));
}

// --- state coming from the server ------------------------------------------

/** Adopts the session state from the `hello` (or from `project.recent`, a subset of it). */
export function adoptSession(state: SessionState | undefined): void {
  if (!state) return;
  batch(() => {
    recentFiles.value = state.recent_files ?? [];
    recentProjects.value = state.recent_projects ?? [];
    hasAutosession.value = Boolean(state.has_autosession);
    if ('project' in state) currentProject.value = state.project ?? null;
  });
  if (state.documents !== undefined && !restoredFromHello) {
    restoredFromHello = true;
    restoreDocuments(state.documents);
  }
}

/**
 * Opens the home screen when there is nothing to show — once, on the first connection.
 *
 * By RPC and not by a local setting: `layout.show` goes through `app.layout`, so the Python
 * echo is emitted as for any other gesture. The condition looks at what is *open*, not what is
 * *recent*: an empty session on first launch and an empty session after closing everything
 * deserve the same screen.
 */
export function showHomeIfEmpty(windowCount: number): void {
  if (homeDecided) return;
  homeDecided = true;
  const vide =
    windowCount === 0 && openScripts.value.length === 0 && openContainers.value.length === 0;
  if (vide) void client.call('layout.show', { panel: 'home' }).catch(() => undefined);
  // Same moment as the home screen, and for the same reason: the first snapshot is through,
  // the panels are mounted, and the tour has something to point at.
  startTourIfFirstRun();
}

let homeDecided = false;

export function connectProject(): void {
  client.onNotification((method, params) => {
    switch (method) {
      case 'project.command': {
        const command = params as ProjectCommand;
        if (command.op === 'request_documents') pendingRequest.value = command.request ?? '';
        else if (command.op === 'restore_documents') restoreDocuments(command.documents);
        break;
      }
      case 'session.changed':
        void refreshRecent();
        break;
      case 'state.changed': {
        // The current project is derived from the domain: `app.open_project` typed in the
        // console must rename the title bar just as a menu click does.
        const snapshot = params as { project?: string | null };
        if ('project' in snapshot) currentProject.value = snapshot.project ?? null;
        break;
      }
      default:
        break;
    }
  });

  // Answers `request_documents`: the server does not know our tabs, we do.
  pendingRequest.subscribe((request) => {
    if (request === null) return;
    const documents = serializeDocuments();
    batch(() => {
      pendingRequest.value = null;
    });
    void client
      .call('project.store_documents', { request, documents })
      .catch((e: unknown) => console.error(e));
  });
}

/** Reset for the tests — modules keep their state between two cases. */
export function resetProjectStateForTests(): void {
  restoredFromHello = false;
  homeDecided = false;
  currentProject.value = null;
  recentFiles.value = [];
  recentProjects.value = [];
  hasAutosession.value = false;
  pendingRequest.value = null;
}
