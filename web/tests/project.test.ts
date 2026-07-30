// The client side of the project dialogue.
//
// What can break unnoticed: not answering `request_documents` (the server would write a project
// with no tabs), or conversely replaying a stale blob over the live state after a mere
// reconnection.

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });
const memory = new Map<string, string>();
vi.stubGlobal('localStorage', {
  getItem: (k: string) => memory.get(k) ?? null,
  setItem: (k: string, v: string) => void memory.set(k, v),
  removeItem: (k: string) => void memory.delete(k),
});

const { client } = await import('../src/api/client');
const {
  adoptSession,
  connectProject,
  currentProject,
  hasAutosession,
  hasUnsavedWork,
  projectName,
  recentFiles,
  recentProjects,
  resetProjectStateForTests,
} = await import('../src/project/project');
const { newScript, openScripts, setScriptText, closeScript, scriptText } = await import(
  '../src/scripts/scripts'
);
const { openContainers } = await import('../src/pipeline/containerEdit');

/** Replays a notification as if it came from the server. */
type Notifier = (method: string, params: unknown) => void;
const notifiers: Notifier[] = [];
vi.spyOn(client, 'onNotification').mockImplementation((handler: Notifier) => {
  notifiers.push(handler);
  return () => undefined;
});
const calls: { method: string; params: unknown }[] = [];
vi.spyOn(client, 'call').mockImplementation(((method: string, params?: unknown) => {
  calls.push({ method, params });
  return Promise.resolve({});
}) as typeof client.call);

connectProject();

function notify(method: string, params: unknown): void {
  for (const handler of notifiers) handler(method, params);
}

beforeEach(() => {
  calls.length = 0;
  for (const doc of [...openScripts.value]) closeScript(doc.id);
  openContainers.value = [];
  resetProjectStateForTests();
});

describe('document request', () => {
  it('answers request_documents with the correlation it received', async () => {
    const id = newScript();
    setScriptText(id, 'x = 1\n');

    notify('project.command', { op: 'request_documents', request: 'd7' });
    await Promise.resolve();

    const response = calls.find((a) => a.method === 'project.store_documents');
    expect(response).toBeDefined();
    const params = response?.params as { request: string; documents: { version: number } };
    expect(params.request).toBe('d7');
    expect(params.documents.version).toBe(1);
  });

  it('restore_documents replaces the live state', () => {
    const id = newScript();
    setScriptText(id, 'old\n');
    notify('project.command', { op: 'request_documents', request: 'd1' });
    const blob = (calls.at(-1)?.params as { documents: unknown }).documents;
    setScriptText(id, 'meanwhile\n');

    notify('project.command', { op: 'restore_documents', documents: blob });

    expect(scriptText(id)).toBe('old\n');
  });
});

describe('session state', () => {
  it('adopts the recents and the current project from the hello', () => {
    adoptSession({
      recent_files: ['/a.fits'],
      recent_projects: ['/p.retina'],
      reopen: false,
      has_autosession: true,
      project: '/p.retina',
      language: null,
      effective_language: 'en',
    });

    expect(recentFiles.value).toEqual(['/a.fits']);
    expect(recentProjects.value).toEqual(['/p.retina']);
    expect(hasAutosession.value).toBe(true);
    expect(currentProject.value).toBe('/p.retina');
  });

  it('restores the documents from the hello exactly once', () => {
    // A reconnection (server restarted, WebSocket dropped) would otherwise replay the last
    // project's blob over whatever the user has typed since.
    const id = newScript();
    setScriptText(id, 'work in progress\n');
    const blob = {
      version: 1,
      scripts: { docs: [], nextId: 1, nextUntitled: 1, activeId: null },
      containers: { docs: [], nextId: 1, nextUntitled: 1 },
      filesRoot: null,
      transcript: [],
      activeTab: null,
    };
    const state = {
      recent_files: [],
      recent_projects: [],
      reopen: false,
      has_autosession: false,
      project: null,
      language: null,
      effective_language: 'en',
      documents: blob,
    };

    adoptSession(state); // first connection: the blob applies
    expect(openScripts.value).toHaveLength(0);

    const survivor = newScript();
    setScriptText(survivor, 'after reconnect\n');
    adoptSession(state); // reconnection: it must overwrite NOTHING

    expect(scriptText(survivor)).toBe('after reconnect\n');
  });

  it('session.changed triggers a re-read of the recents', () => {
    notify('session.changed', {});

    expect(calls.some((a) => a.method === 'project.recent')).toBe(true);
  });

  it('tracks the current project from the snapshot — console included', () => {
    // `app.open_project` typed in the console must rename the title bar just as a menu click
    // does.
    notify('state.changed', { project: '/from/the/console.retina' });

    expect(currentProject.value).toBe('/from/the/console.retina');
  });
});

describe('unsaved work', () => {
  it('detects a modified script', () => {
    expect(hasUnsavedWork()).toBe(false);
    const id = newScript();
    setScriptText(id, 'dirty\n');
    expect(hasUnsavedWork()).toBe(true);
  });

  it('detects a modified recipe', () => {
    openContainers.value = [
      { id: 'container:1', name: null, title: 'Recipe 1', steps: [], dirty: true },
    ];
    expect(hasUnsavedWork()).toBe(true);
  });
});

describe('displayed name', () => {
  it('strips the suffix and the folder', () => {
    expect(projectName('/data/astro/M31 wide field.retina')).toBe('M31 wide field');
    expect(projectName('C:\\astro\\M42.retina')).toBe('M42');
    expect(projectName(null)).toBe('');
  });
});
