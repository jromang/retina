// Project & session, end to end.
//
// The one place where the whole chain is exercised: browser → WebSocket → server → domain →
// HDF5 file, and back. What the lower-level tests cannot show is that the document blob really
// makes the round trip — the server *asks* the client for it during the write job, and *gives*
// it back on open.
//
// Projects are written into the run's `RETINA_CONFIG_DIR` (`web/.e2e-config`), which the
// Playwright configuration already isolates: nothing lands in the real config.

import { expect, test, type Page } from '@playwright/test';

const TOKEN = 'playwright-e2e';

/** Text of the unsaved buffer — with no character Monaco would re-indent. */
const MARKER = 'marqueur_du_tampon_non_enregistre = 42';

type TestRpc = (method: string, params: unknown) => Promise<unknown>;

async function rpc<T>(page: Page, method: string, params: unknown = {}): Promise<T> {
  return (await page.evaluate(
    (call) =>
      (window as unknown as { __retinaTestRpc: TestRpc }).__retinaTestRpc(call.method, call.params),
    { method, params },
  )) as T;
}

async function runPython(page: Page, code: string): Promise<void> {
  const result = await rpc<{ status: string; error?: string }>(page, 'console.execute', { code });
  expect(result.status, result.error ?? '').toBe('ok');
}

/** Working path of the project, inside the run's isolated config directory. */
async function projectPath(page: Page, name: string): Promise<string> {
  const result = await rpc<{ status: string; repr?: string | null }>(page, 'console.execute', {
    code: `import retina.paths as _p; str(_p.config_path(${JSON.stringify(name)}))`,
  });
  expect(result.status).toBe('ok');
  // `repr` of a Python str: strip the quotes, then **unescape the backslash**. On Windows the
  // path contains some, and `repr` doubles them: without that last step we were comparing
  // `C:\\Users\\…` to `C:\Users\…`, which can never match.
  return (result.repr ?? '')
    .replace(/^'|'$/g, '')
    .replace(/^"|"$/g, '')
    .replace(/\\\\/g, '\\');
}

async function connect(page: Page): Promise<void> {
  await page.goto(`/?t=${TOKEN}`);
  // Same reason as in `smoke.spec.ts`: the application mounts after `load` ever since the
  // language is resolved before the first render, and the RPC bridge needs the token it writes.
  await page.locator('.workbench').waitFor({ state: 'visible' });
  await page.evaluate(() => {
    const token = sessionStorage.getItem('retina.token') ?? '';
    const socket = new WebSocket(`ws://${location.host}/ws?t=${token}`);
    let nextId = 1;
    const waiting = new Map<number, (value: unknown) => void>();
    socket.addEventListener('message', (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data);
      if (data.id && waiting.has(data.id)) {
        waiting.get(data.id)!(
          data.error ? Promise.reject(new Error(data.error.message)) : data.result,
        );
        waiting.delete(data.id);
      }
    });
    const ready = new Promise<void>((resolve) => socket.addEventListener('open', () => resolve()));
    (window as unknown as { __retinaTestRpc: unknown }).__retinaTestRpc = async (
      method: string,
      params: unknown,
    ) => {
      await ready;
      const id = nextId++;
      socket.send(JSON.stringify({ jsonrpc: '2.0', id, method, params }));
      return new Promise((resolve) => waiting.set(id, resolve));
    };
  });
  await expect(page.locator('.status-bar')).toContainText('connecté');
}

test.beforeEach(async ({ page }) => {
  await connect(page);
  // A fresh session for each scenario: otherwise the tests would hand each other their recent
  // files and their current project.
  await runPython(page, 'app.close_project()');
});

test('an unsaved script and a recipe survive a reload', async ({ page }) => {
  const path = await projectPath(page, 'e2e-documents.retina');

  // An image, so that the project has some domain to carry too.
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina import Image\n'
      + 'app.new_window(Image(np.full((32, 48, 1), 0.5, np.float32)), window_id="E2E01")\n',
  );

  // An **unsaved** script, typed in the editor — what earlier versions lost on every reload.
  // We go through the real interface: the served bundle does not expose its modules.
  await page.keyboard.press('Control+Shift+P');
  await page.locator('.palette input').fill('nouveau script');
  await page.locator('.palette-item').first().click();
  const editor = page.locator('.script-tab .monaco-editor');
  await expect(editor).toBeVisible();
  await editor.click();
  await page.keyboard.type(MARKER);
  const tab0 = page.locator('.dv-tab', { hasText: 'Sans titre' });
  await expect(tab0).toContainText('●'); // never saved

  await rpc(page, 'project.save', { path });
  await expect
    .poll(async () => (await rpc<{ project: string | null }>(page, 'state.snapshot')).project)
    .toBe(path);

  await connect(page);
  await rpc(page, 'project.open', { path });

  // The tab comes back, marked as modified, with its text intact.
  const tab = page.locator('.dv-tab', { hasText: 'Sans titre' });
  await expect(tab).toBeVisible();
  await expect(tab).toContainText('●');
  // …and its content with it: Monaco is recreated from the text in the blob.
  await expect(page.locator('.script-tab .monaco-editor')).toContainText(MARKER);

  // And so does the domain: the window is there.
  const snapshot = await rpc<{ windows: { id: string }[] }>(page, 'state.snapshot');
  expect(snapshot.windows.map((w) => w.id)).toContain('E2E01');
});

test('the full history comes back — undo and redo included', async ({ page }) => {
  const path = await projectPath(page, 'e2e-historique.retina');

  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina import Image, Invert, Rescale\n'
      + 'w = app.new_window(Image(np.full((16, 16, 1), 0.5, np.float32)), window_id="Hist01")\n'
      + 'Invert().execute_on(w.main_view)\n'
      + 'Rescale().execute_on(w.main_view)\n'
      + 'w.main_view.undo()\n',
  );

  await rpc(page, 'project.save', { path });
  await expect
    .poll(async () => (await rpc<{ project: string | null }>(page, 'state.snapshot')).project)
    .toBe(path);
  await runPython(page, 'app.close_project()');
  await rpc(page, 'project.open', { path });

  const view = await expect
    .poll(async () => {
      const snap = await rpc<{ windows: { id: string; views: { history: unknown }[] }[] }>(
        page,
        'state.snapshot',
      );
      return snap.windows.find((w) => w.id === 'Hist01')?.views[0]?.history ?? null;
    })
    .not.toBeNull()
    .then(async () => {
      const snap = await rpc<{
        windows: { id: string; views: { history: { labels: string[]; index: number; can_redo: boolean } }[] }[];
      }>(page, 'state.snapshot');
      return snap.windows.find((w) => w.id === 'Hist01')!.views[0]!.history;
    });

  expect(view.labels).toEqual(['initial', 'Invert', 'Rescale']);
  expect(view.index).toBe(1);
  // Redo is held in reserve: embedding the history states — the equivalent of shipping the swap
  // files inside the project file — is the whole point.
  expect(view.can_redo).toBe(true);
});

test('the home screen opens on an empty session and lists the recent projects', async ({ page }) => {
  const path = await projectPath(page, 'e2e-accueil.retina');
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina import Image\n'
      + 'app.new_window(Image(np.full((16, 16, 1), 0.25, np.float32)), window_id="Acc01")\n',
  );
  await rpc(page, 'project.save', { path });
  await expect
    .poll(async () => (await rpc<{ project: string | null }>(page, 'state.snapshot')).project)
    .toBe(path);

  // Empty session: no window left, no document left.
  await runPython(page, 'app.close_project()');

  await connect(page);

  const home = page.locator('.dv-tab', { hasText: 'Accueil' });
  await expect(home).toBeVisible();
  // And the project we have just written shows up there, clickable.
  await expect(page.getByRole('button', { name: 'e2e-accueil.retina' })).toBeVisible();
});
