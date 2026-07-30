// End-to-end smoke test for the web shell.
//
// The frontend counterpart of `scripts/gui_smoke.py`: we do not check pixel-perfect rendering,
// but that the whole chain holds — browser → WebSocket → server → domain, and back. This is the
// only test that exercises real JavaScript in a real browser; anything that can be checked lower
// down (protocol, mathematical parity) is already covered by pytest and vitest, and has no
// business here.
//
// The scenario goes **through the console** to create its image: that avoids depending on a test
// FITS file, and checks the console-completeness pillar along the way.

import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { expect, test, type Page } from '@playwright/test';

const TOKEN = 'playwright-e2e';

/**
 * Throwaway working path, **valid on the platform that runs the server**.
 *
 * The scenarios used to hardcode `/tmp/...`. On Windows, Python does create that directory (it
 * lands in `C:\tmp`), but the server **rejects** it: `fs.list` requires an absolute path, and
 * `Path('/tmp/x').is_absolute()` is `False` there, for lack of a drive letter. The file explorer
 * therefore stayed empty and the test timed out on a tree row that would never come.
 *
 * Since Playwright runs on the same machine as the server, `os.tmpdir()` is the right answer on
 * both sides.
 */
function tempPath(name: string): string {
  return join(tmpdir(), name);
}

type TestRpc = (method: string, params: unknown) => Promise<unknown>;

/** Calls an RPC method from the page — same server, therefore same `app`. */
async function rpc<T>(page: Page, method: string, params: unknown = {}): Promise<T> {
  return (await page.evaluate(
    (call) =>
      (window as unknown as { __retinaTestRpc: TestRpc }).__retinaTestRpc(call.method, call.params),
    { method, params },
  )) as T;
}

/** Runs Python in the application console and checks that it succeeded. */
async function runPython(page: Page, code: string): Promise<void> {
  const result = await rpc<{ status: string; error?: string }>(page, 'console.execute', { code });
  expect(result.status, result.error ?? '').toBe('ok');
}

/**
 * Answers the input modal (`ui/prompts.ts`), which replaced `globalThis.prompt`.
 *
 * The browser dialog blocked the event loop and is not guaranteed inside an embedded WebView —
 * hence the modal, and hence this helper: there is no longer a `dialog` event to intercept, only
 * DOM.
 */
function answerPrompt(page: Page, value: string): Promise<void> {
  return (async () => {
    const field = page.locator('[role="dialog"] input[type="text"]');
    await field.waitFor({ state: 'visible' });
    await field.fill(value);
    await page.locator('[role="dialog"] .btn-primary').click();
  })();
}

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    // The 404/409s from the pixel endpoints are races TOLERATED BY DESIGN (view closed, or
    // generation gone stale between the snapshot and the request — the client swallows them
    // silently), yet Chromium still logs "Failed to load resource". Filter ONLY those messages:
    // any other 4xx/5xx, or the same error outside /api/, remains fatal to the test.
    const url = message.location().url ?? '';
    if (
      /Failed to load resource.*(404|409)/.test(message.text())
      && /\/api\/(pixels|mask|rtp)/.test(url)
    ) {
      return;
    }
    errors.push(message.text());
  });
  page.on('pageerror', (error) => errors.push(String(error)));
  (page as Page & { __errors: string[] }).__errors = errors;

  await page.goto(`/?t=${TOKEN}`);
  // Wait for the mount, not merely the `load` event. Ever since the language is resolved before
  // the first render (`src/main.tsx` → `await import('./app')`), the application mounts **after**
  // `load`: the bridge below then read a still-empty `sessionStorage`, opened its WebSocket
  // without a token, and every RPC call in the test timed out after fifteen seconds — with
  // nothing pointing at the cause.
  await page.locator('.workbench').waitFor({ state: 'visible' });

  // Test RPC bridge: a parallel WebSocket, talking to the same server hence the same `app`.
  await page.evaluate(() => {
    const token = sessionStorage.getItem('retina.token') ?? '';
    const socket = new WebSocket(`ws://${location.host}/ws?t=${token}`);
    let nextId = 1;
    const waiting = new Map<number, (value: unknown) => void>();
    socket.addEventListener('message', (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data);
      if (data.id && waiting.has(data.id)) {
        waiting.get(data.id)!(data.error ? Promise.reject(new Error(data.error.message)) : data.result);
        waiting.delete(data.id);
      }
    });
    const ready = new Promise<void>((resolve) =>
      socket.addEventListener('open', () => resolve()),
    );
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
});

test.afterEach(async ({ page }) => {
  const errors = (page as Page & { __errors?: string[] }).__errors ?? [];
  expect(errors, `console errors: ${errors.join(' | ')}`).toHaveLength(0);
});

test('the shell mounts and connects to the domain', async ({ page }) => {
  await expect(page.locator('.status-bar')).toContainText('connecté');
  // The catalogue did travel across the protocol. Since the list became virtualized, only the
  // visible window is in the DOM — so we assert "some rows rendered", not all 115.
  await expect(page.locator('.tree-group').first()).toBeVisible();
  const count = await page.locator('.tree-row').count();
  expect(count).toBeGreaterThan(15);
});

test('an image created from the console shows up and renders', async ({ page }) => {
  await runPython(
    page,
    'import numpy as np\n' +
      'from retina.model.image import Image\n' +
      'y, x = np.mgrid[0:200, 0:300].astype(np.float32)\n' +
      'data = np.stack([x / 300 * 0.5 + 0.1] * 3, axis=-1).astype(np.float32)\n' +
      "app.new_window(Image(data), window_id='E2E')\n" +
      'app.compute_auto_stf()',
  );

  // The window surfaces in the snapshot, hence in the window tree…
  await page.locator('.activity-item[title*="Fenêtres"]').click();
  await expect(page.locator('.tree-row', { hasText: 'E2E' })).toBeVisible();

  // …and the viewport really does render non-zero pixels. The display canvas is a 2D canvas fed
  // from the shared GL context: `getImageData` reads it directly — no more smuggled-in
  // `preserveDrawingBuffer`, and the 2D bitmap persists between frames.
  const drawn = await page.evaluate(async () => {
    const canvas = document.querySelector('canvas');
    if (!canvas) return -1;
    // Wait two frames: the texture upload is asynchronous.
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const ctx = canvas.getContext('2d');
    if (!ctx) return -2;
    const pixels = ctx.getImageData(
      Math.floor(canvas.width / 2) - 5, Math.floor(canvas.height / 2) - 5, 10, 10,
    ).data;
    let sum = 0;
    for (let i = 0; i < pixels.length; i += 4) sum += pixels[i]! + pixels[i + 1]! + pixels[i + 2]!;
    return sum;
  });
  // -1/-2 = no canvas or no context; 0 = black image.
  expect(drawn).toBeGreaterThan(0);
});

/** RGB sum of a 10×10 square at the center of the first visible canvas (the 2D display canvas). */
async function centerSum(page: Page): Promise<number> {
  return page.evaluate(async () => {
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const canvas = [...document.querySelectorAll('canvas')].find((c) => c.clientWidth > 0);
    const ctx = canvas?.getContext('2d');
    if (!ctx || !canvas) return -1;
    const pixels = ctx.getImageData(
      Math.floor(canvas.width / 2) - 5, Math.floor(canvas.height / 2) - 5, 10, 10,
    ).data;
    let sum = 0;
    for (let i = 0; i < pixels.length; i += 4) sum += pixels[i]! + pixels[i + 1]! + pixels[i + 2]!;
    return sum;
  });
}

test('twenty-five open windows: each one renders, none dies', async ({ page }) => {
  // The old world: one WebGL2 context per viewport, and the browser keeps only ~16 of them alive
  // — the seventeenth window silently killed the first, which stayed black forever. The shared
  // context removes the ceiling; this test is its acceptance criterion.
  test.setTimeout(120_000);
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      + 'for w in list(app.windows): app.close_window(w)\n'
      + 'for i in range(25):\n'
      + "    app.new_window(Image(np.full((64, 64, 3), 0.55, dtype=np.float32)), window_id=f'Ctx{i:02d}')",
  );

  // Every window, once activated, must render non-black pixels — including the first ones
  // opened, the very ones the old world sacrificed.
  for (const i of [0, 5, 12, 18, 24]) {
    await runPython(page, `app.set_active_window(app.view('Ctx${i.toString().padStart(2, '0')}').window)`);
    await expect(page.locator('.status-bar')).toContainText(`Ctx${i.toString().padStart(2, '0')}`);
    await expect.poll(() => centerSum(page)).toBeGreaterThan(0);
  }
  // Zero console errors — afterEach checks that, but it is worth saying: this is where
  // "texImage2D failed (GL 0x9242)" used to rain down before the refactor.
});

test('a lost GL context restores itself, viewports included', async ({ page }) => {
  // The rare but real case: GPU reset, driver update. Before the refactor, a viewport whose
  // context was lost stayed black forever — nothing handled it anywhere. The shared context
  // concentrates the loss in one place: preventDefault, cache invalidation, recompilation on
  // restore, and `glEpoch` wakes up the loading effects that re-fetch from the server. The test
  // also proves, incidentally, that the lost/restored events do fire on a canvas never inserted
  // into the DOM.
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      + 'for w in list(app.windows): app.close_window(w)\n'
      + "app.new_window(Image(np.full((80, 120, 3), 0.35, dtype=np.float32)), window_id='Reset')",
  );
  await expect.poll(() => centerSum(page)).toBeGreaterThan(0);

  await page.evaluate(() => {
    type Hook = { gl: WebGL2RenderingContext };
    const shared = (window as unknown as { __retinaGL: Hook }).__retinaGL;
    const ext = shared.gl.getExtension('WEBGL_lose_context');
    if (!ext) throw new Error('WEBGL_lose_context unavailable');
    ext.loseContext();
    // Restoration is asynchronous on the browser side; the delay imitates a real reset.
    setTimeout(() => ext.restoreContext(), 150);
  });

  // `centerSum > 0` would not be enough: the 2D canvas keeps its last blit, so the old image
  // would let the test pass even on a dead context. We therefore change the pixels AFTER the
  // restore: seeing them on screen proves that the recompiled context accepts new uploads and
  // that `glEpoch` did wake the loading effects up.
  const dark = await centerSum(page);
  await runPython(
    page,
    'from retina import PixelMath\n'
      + "app.apply(PixelMath(expression='img*0 + 0.95'))",
  );
  await expect
    .poll(() => centerSum(page), { timeout: 15000 })
    .toBeGreaterThan(dark * 1.3);
});

test('window churn: opening, closing and reopening exhausts nothing', async ({ page }) => {
  // The other half of the original bug: dispose() did not release the context, so opening and
  // closing windows over a session drained the pool even with three windows open. With the
  // shared context there is nothing left to drain — this test locks that in.
  test.setTimeout(120_000);
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      + 'for w in list(app.windows): app.close_window(w)\n'
      + 'for i in range(20):\n'
      + "    app.new_window(Image(np.full((64, 64, 3), 0.55, dtype=np.float32)), window_id=f'Churn{i:02d}')\n"
      + 'for i in range(15):\n'
      + "    app.close_window([w for w in app.windows if w.id == f'Churn{i:02d}'][0])\n"
      + 'for i in range(10):\n'
      + "    app.new_window(Image(np.full((64, 64, 3), 0.55, dtype=np.float32)), window_id=f'Rouvre{i:02d}')",
  );

  await runPython(page, "app.set_active_window(app.view('Rouvre09').window)");
  await expect(page.locator('.status-bar')).toContainText('Rouvre09');
  await expect.poll(() => centerSum(page)).toBeGreaterThan(0);

  // A survivor of the first batch renders too.
  await runPython(page, "app.set_active_window(app.view('Churn17').window)");
  await expect(page.locator('.status-bar')).toContainText('Churn17');
  await expect.poll(() => centerSum(page)).toBeGreaterThan(0);
});

test('applying a process pushes history and the echo, undo goes back', async ({ page }) => {
  await runPython(
    page,
    'import numpy as np\n' +
      'from retina.model.image import Image\n' +
      "app.new_window(Image(np.full((64, 64, 3), 0.4, dtype=np.float32)), window_id='E2E2')",
  );

  const job = await rpc<{ job: string }>(page, 'process.run', {
    process_id: 'Invert',
    params: {},
  });
  expect(job.job).toMatch(/^j\d+$/);

  // The domain history carries the entry…
  await expect
    .poll(async () => {
      const snapshot = await rpc<{ windows: Array<{ id: string; views: Array<{ history: { labels: string[] } }> }> }>(
        page,
        'state.snapshot',
      );
      const win = snapshot.windows.find((w) => w.id === 'E2E2');
      return win?.views[0]?.history.labels ?? [];
    })
    .toContain('Invert');

  // …and the interface shows it. A two-step assertion, scoped to the sidebar: the first `expect`
  // proves the panel switched, the second that its content is up to date. Without the scope,
  // `Invert` would also be found in the process explorer — the test would pass while proving
  // nothing. This pair is what flushed out the `Broadcaster.mark_state_dirty` race (snapshot lost
  // when a worker thread scheduled the flush): the interface stayed stuck on `initial` while the
  // domain did carry the entry.
  await page.locator('.activity-item[title*="Historique"]').click();
  await expect(page.locator('.sidebar .panel-title')).toContainText('Historique');
  await expect(page.locator('.sidebar .tree-row', { hasText: 'Invert' })).toBeVisible();

  expect(await rpc<boolean>(page, 'app.undo')).toBe(true);
  await expect
    .poll(async () => {
      const snapshot = await rpc<{ windows: Array<{ id: string; views: Array<{ history: { index: number } }> }> }>(
        page,
        'state.snapshot',
      );
      return snapshot.windows.find((w) => w.id === 'E2E2')?.views[0]?.history.index;
    })
    .toBe(0);
});

test('the command palette shows the equivalent Python code', async ({ page }) => {
  await page.keyboard.press('Control+Shift+P');
  await expect(page.locator('.palette input')).toBeFocused();

  await page.locator('.palette input').fill('auto');
  const item = page.locator('.palette-item').first();
  await expect(item).toContainText('Auto-stretch');
  // This is the signature device: you learn the API by reading the palette.
  await expect(item.locator('.python')).toContainText('app.compute_auto_stf()');

  await page.keyboard.press('Escape');
  await expect(page.locator('.palette')).toHaveCount(0);
});

test('collapsing then expanding the sidebar reopens the same panel', async ({ page }) => {
  // The hard part about zones: the memory of which panel to reopen lives on the server side, and
  // this test crosses it end to end. Without it, we would fall back to the default Explorer.
  await runPython(page, "app.layout.activate('history')");
  await expect(page.locator('.sidebar .panel-title')).toContainText('Historique');

  await page.locator('.title-action[data-zone="sidebar"]').click();
  await expect(page.locator('.sidebar')).toHaveCount(0);

  await page.locator('.title-action[data-zone="sidebar"]').click();
  await expect(page.locator('.sidebar .panel-title')).toContainText('Historique');
});

test('a title-bar menu acts on the domain', async ({ page }) => {
  // Menu → RPC → app.layout → Python mirror: the full loop, in one click.
  await page.locator('.menubar-item', { hasText: 'Panneaux' }).click();
  await page
    .locator('.menu-item', { hasText: 'Basculer : Panneau inférieur' })
    .click();

  await expect(page.locator('.bottom')).toHaveCount(0);
  expect(await rpc<boolean>(page, 'layout.is_zone_visible', { zone: 'bottom' })).toBe(false);
  // (That the action really produces `app.layout.toggle_zone('bottom')` in the console is checked
  // closer to the source, on the pytest side:
  // tests/server/test_layout.py::test_toggle_zone_echoe_le_python.)
});

test('hovering switches menus when a menu is already open', async ({ page }) => {
  // The signature gesture of a menu bar: without it, you would have to click every title.
  await page.locator('.menubar-item', { hasText: 'Fichier' }).click();
  await expect(page.locator('.menu-dropdown')).toContainText('Ouvrir une image');

  await page.locator('.menubar-item', { hasText: 'Vue' }).hover();
  await expect(page.locator('.menu-dropdown')).toContainText('Zoom 1:1');

  await page.keyboard.press('Escape');
  await expect(page.locator('.menu-dropdown')).toHaveCount(0);
});

test('every process carries its icon, in the explorer and in the menus', async ({ page }) => {
  // The icons come from `/api/icons/<name>.svg`, resolved on the Python side by
  // `resources/icons/registry.py`. A regression we lived through: the frontend showed one generic
  // codicon, identical for all 115 processes, and nothing at all in the menus.
  //
  // The suite shares a single server, hence a single `app`: an earlier test may have switched the
  // sidebar panel. We set the state we need rather than inheriting it.
  await runPython(page, "app.layout.activate('explorer')");
  const explorer = page.locator('.sidebar .tabler-icon');
  await expect(explorer.first()).toBeVisible();
  // Virtualized list: only the visible window is in the DOM.
  expect(await explorer.count()).toBeGreaterThan(15);

  // Genuinely distinct icons, not the same one 115 times over.
  const urls = await explorer.evaluateAll((nodes) =>
    nodes.map((n) => (n as HTMLElement).style.getPropertyValue('--tabler-icon')),
  );
  expect(new Set(urls).size).toBeGreaterThan(5);

  await page.locator('.menubar-item', { hasText: 'Process' }).click();
  await page.locator('.menu-item').first().hover();
  await expect(page.locator('.menu-dropdown .tabler-icon').first()).toBeVisible();
});

test('dragging the title bar asks the shell to move the window', async ({ page }) => {
  // The window chrome only exists in the native shell; we simulate it to check the **wiring**. A
  // regression we lived through: the double-click guard tested `event.detail` on a `pointerdown`,
  // where it is always 0 — the drag never started.
  await page.addInitScript(() => {
    (window as unknown as { __RETINA_SHELL__: boolean }).__RETINA_SHELL__ = true;
    (window as unknown as { __calls: string[] }).__calls = [];
    (window as unknown as { retinaShell: unknown }).retinaShell = {
      invoke: (cmd: string) => {
        (window as unknown as { __calls: string[] }).__calls.push(cmd);
        return Promise.resolve(cmd === 'window_is_maximized' ? false : true);
      },
    };
  });
  await page.reload();
  await expect(page.locator('.window-controls')).toBeVisible();

  const calls = () => page.evaluate(() => (window as unknown as { __calls: string[] }).__calls);
  await page.evaluate(() => {
    (window as unknown as { __calls: string[] }).__calls = [];
  });

  const drag = page.locator('.title-drag').first();
  const box = (await drag.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.up();
  expect(await calls()).toContain('window_drag');

  // …and a click on a button in the bar must most certainly not move the window.
  await page.evaluate(() => {
    (window as unknown as { __calls: string[] }).__calls = [];
  });
  await page.locator('.menubar-item').first().click();
  await page.keyboard.press('Escape');
  expect(await calls()).not.toContain('window_drag');
});

test('the command center opens the palette', async ({ page }) => {
  await page.locator('.command-center').click();
  await expect(page.locator('.palette input')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.locator('.palette')).toHaveCount(0);
});

test('layout driven from the domain moves the panels', async ({ page }) => {
  // Typed "in the console", the way a script would — the interface must follow.
  await runPython(page, "app.layout.activate('history')");
  // Scoped to the sidebar: the right zone also has a `.panel-title` (STF).
  await expect(page.locator('.sidebar .panel-title')).toContainText('Historique');

  await runPython(page, "app.layout.toggle('rtp')");
  await expect(page.locator('.bottom-tab', { hasText: 'Aperçu temps réel' })).toBeVisible();
});

test('the preprocessing tab opens from the console', async ({ page }) => {
  // Parity: no GUI action without an API equivalent. If this line opens the tab, then the wizard
  // has no power of its own — it is driven by the same `app.layout` as everything else.
  // Preprocessing itself is exercised end to end by pytest
  // (tests/server/test_pipeline_parity.py); redoing it here would be slow without proving
  // anything more about the browser.
  await runPython(page, "app.layout.show('pipeline')");

  await expect(page.getByRole('button', { name: 'Parcourir…' })).toBeVisible();
  await expect(page.getByText('Aucun dossier choisi')).toBeVisible();

  await runPython(page, "app.layout.hide('pipeline')");
  await expect(page.getByRole('button', { name: 'Parcourir…' })).toHaveCount(0);
});

test('the detected-groups table can be corrected with the mouse', async ({ page }) => {
  // Classification is an inference: it gets things wrong, and fixing it must stay an in-place
  // gesture — a menu on the row, not a removal followed by a typed re-add.
  // The test exercises the full loop — browser → `pipeline.reclassify` → domain → back.
  const folder = tempPath('retina-e2e-pipeline');
  await runPython(
    page,
    'import os, shutil\n' +
      'from retina.pipeline.synthetic import make_dataset\n' +
      `shutil.rmtree(${JSON.stringify(folder)}, ignore_errors=True)\n` +
      `os.makedirs(${JSON.stringify(folder)})\n` +
      `make_dataset(${JSON.stringify(folder)}, "mono", filters=("L",))`,
  );

  await runPython(page, "app.layout.show('pipeline')");
  // Outside the native shell, `askPath` falls back to the input modal — we answer in its place.
  await page.getByRole('button', { name: 'Parcourir…' }).click();
  await answerPrompt(page, folder);

  const types = page.locator('table select');
  const kinds = () => types.evaluateAll((els) => els.map((e) => (e as HTMLSelectElement).value));
  await expect.poll(kinds).toEqual(['light', 'flat', 'dark', 'bias']);

  // Reclassify the biases as flats: they leave their row to join another one.
  await types.nth(3).selectOption('flat');
  await expect.poll(kinds).toEqual(['light', 'flat', 'flat', 'dark']);

  // Excluding a group strikes out its count — and stays reversible, unlike the "Remove Selected"
  // of other suites.
  // `click` and not `check`: the checkbox is not local state, it reflects the inventory the
  // server sends back — so it only flips once the round trip returns, like the rest of the
  // interface (see `layoutClient`).
  const include = page.locator('table input[type="checkbox"]');
  await include.first().click();
  await expect(include.first()).not.toBeChecked();
  await include.first().click();
  await expect(include.first()).toBeChecked();
});

test('the calibration status follows the corrections', async ({ page }) => {
  // Grouping and matching come from the domain: excluding the flats must show up immediately on
  // the lights row, using the very rule that will run later.
  const folder = tempPath('retina-e2e-calib');
  await runPython(
    page,
    'import os, shutil\n' +
      'from retina.pipeline.synthetic import make_dataset\n' +
      `shutil.rmtree(${JSON.stringify(folder)}, ignore_errors=True)\n` +
      `os.makedirs(${JSON.stringify(folder)})\n` +
      `make_dataset(${JSON.stringify(folder)}, "mono", filters=("L",))`,
  );

  await runPython(page, "app.layout.show('pipeline')");
  await page.getByRole('button', { name: 'Parcourir…' }).click();
  await answerPrompt(page, folder);

  const lights = page.locator('table tbody tr').first();
  await expect(lights).toContainText('dark + flat');

  // The chain unfolds under the row, with no separate window and no pre-selection.
  await page.getByRole('button', { name: /^Chaîne de calibration de light_L/ }).click();
  const chain = page.locator('table tbody tr').nth(1);
  await expect(chain).toContainText('4 × Lights');
  await expect(chain).toContainText('dark_5s_bin1_g120_m10C');
  await expect(chain).toContainText('3 frames'); // the master's frame count, not just its key
  await expect(chain).toContainText('flat_L_bin1_g120_m10C');
  await expect(chain).toContainText('calibrées');

  // Exclude the flats group: the lights lose their flat, and say so.
  await page.getByLabel('Inclure Flats').click();
  await expect(lights).toContainText('sans flat');
});

test('the plan announces the cumulated exposure and the disk space to expect', async ({ page }) => {
  // The two numbers you want to read before three hours of computation, and that no other screen
  // gives you. Comparable tools bury them in a diagnostics modal.
  const folder = tempPath('retina-e2e-produits');
  await runPython(
    page,
    'import os, shutil\n' +
      'from retina.pipeline.synthetic import make_dataset\n' +
      `shutil.rmtree(${JSON.stringify(folder)}, ignore_errors=True)\n` +
      `os.makedirs(${JSON.stringify(folder)})\n` +
      `make_dataset(${JSON.stringify(folder)}, "mono", filters=("L",))`,
  );

  await runPython(page, "app.layout.show('pipeline')");
  await page.getByRole('button', { name: 'Parcourir…' }).click();
  await answerPrompt(page, folder);
  await page.getByRole('button', { name: 'Générer le plan' }).click();

  const section = page.locator('section').filter({ hasText: 'Ce que vous obtiendrez' });
  await expect(section).toContainText('20 s'); // 4 exposures of 5 s
  await expect(section).toContainText('À écrire');
  await expect(section).toContainText('libres');
});

test('preprocessing is reachable from the activity bar', async ({ page }) => {
  // This is where a session starts: it must be visible at all times, not drowned among eleven
  // entries in the "Panels" menu.
  // The icon **toggles**: start from a known state, otherwise the test depends on whatever an
  // earlier scenario left open — panel visibility lives on the server side, so it persists from
  // one test to the next. The click would then close the panel instead of opening it.
  await runPython(page, "app.layout.hide('pipeline')");
  await page.locator('.activity-bar .activity-item[title^="Pré-traitement"]').click();

  await expect(page.getByRole('button', { name: 'Parcourir…' })).toBeVisible();
});

test('sorting frames: from the wizard to the selector, a rejection does not re-measure', async ({
  page,
}, testInfo) => {
  // The whole journey, through a real browser: preprocess, look at the measurements, exclude an
  // exposure, observe that re-running only recomputes the integration.
  // The synthetic dataset is tiny (13 files of 64 KB) and is generated from the console — the
  // same device as the rest of the file, with console-completeness checked along the way.
  test.setTimeout(180_000);
  const raws = testInfo.outputPath('brutes');

  await runPython(
    page,
    'from retina.pipeline.synthetic import make_dataset\n' +
      `make_dataset(${JSON.stringify(raws)}, 'mono', filters=('L',))`,
  );

  // Without the native shell, folder selection falls back to `prompt()` — the browser's accepted
  // degraded mode, and here our entry point. The icon **toggles**: we start from a known state,
  // otherwise the click closes whatever an earlier scenario left open (panel visibility lives on
  // the server side, so it persists from one test to the next).
  await runPython(page, "app.layout.hide('pipeline')");
  await page.locator('.activity-bar .activity-item[title^="Pré-traitement"]').click();
  await page.getByRole('button', { name: 'Parcourir…' }).click();
  await answerPrompt(page, raws);

  await expect(page.getByRole('button', { name: 'Générer le plan' })).toBeEnabled();
  await page.getByRole('button', { name: 'Générer le plan' }).click();
  await page.getByRole('button', { name: 'Lancer' }).click();

  // The report arrives with `job.done` — nothing to poll for.
  await expect(page.getByRole('button', { name: /Trier les frames|Revoir la sélection/ }))
    .toBeVisible({ timeout: 120_000 });
  await page.getByRole('button', { name: /Trier les frames|Revoir la sélection/ }).click();

  // The table carries one row per exposure, with its measurements.
  const table = page.locator('table').filter({ has: page.getByText('Excentr.') });
  await expect(table).toBeVisible();
  const rows = table.locator('tbody tr');
  await expect.poll(async () => rows.count()).toBeGreaterThan(1);

  // Reject an exposure: the box unchecked, the reason displayed, the cumulated exposure melting.
  const firstRow = rows.first();
  await firstRow.locator('input[type="checkbox"]').uncheck();
  await expect(firstRow).toContainText('écartée à la main');

  // You judge an exposure by **looking** at it, not merely by reading its FWHM: every row must
  // open its frame. Without that gesture, the screen would be a mere spreadsheet.
  const before = (await rpc<{ windows: unknown[] }>(page, 'state.snapshot')).windows.length;
  await firstRow.getByRole('button', { name: 'Ouvrir' }).click();
  await expect
    .poll(async () => (await rpc<{ windows: unknown[] }>(page, 'state.snapshot')).windows.length)
    .toBe(before + 1);

  // And above all: re-running does not re-measure. That is what decoupling measurement from
  // evaluation buys, and the only way to see it end to end.
  const report = await rpc<{ skipped: string[]; executed: string[] }>(page, 'pipeline.report');
  expect(report.skipped.length + report.executed.length).toBeGreaterThan(0);
});

test('the comparison gestures are reachable from the palette', async ({ page }) => {
  // The project rule: every expert gesture keeps an explicit path. The A/B toggle and linked
  // views only existed in the code — a key nothing advertised.
  await page.keyboard.press('Control+Shift+P');
  await page.locator('.palette input').fill('lier les vues');
  await expect(page.locator('.palette-item').first()).toContainText('Lier les vues');
  await expect(page.locator('.palette-item').first().locator('.python')).toContainText(
    'app.link_viewports()',
  );

  await page.locator('.palette input').fill('comparer');
  await expect(page.locator('.palette-item').first()).toContainText('Comparer A/B');
  await page.keyboard.press('Escape');
});

// --- Script mode -------------------------------------------------------------

test('a script is written, run, and its output lands in the console', async ({ page }) => {
  // The whole journey: new tab → Monaco → F5 → `console.execute` → transcript. This is also what
  // checks that execution really goes through the shared console rather than a parallel channel:
  // the output must appear where the user looks for it.
  await page.keyboard.press('Control+Shift+P');
  await page.locator('.palette input').fill('nouveau script');
  await page.locator('.palette-item').first().click();

  // `.script-tab` and not "the last Monaco on the page": the console prompt is one too, and that
  // is where the keystrokes used to land.
  const editor = page.locator('.script-tab .monaco-editor');
  await expect(editor).toBeVisible();
  await editor.click();
  await page.keyboard.type("print('bonjour depuis un script')");
  await page.keyboard.press('F5');

  await expect(page.locator('.bottom')).toContainText('bonjour depuis un script');
});

test('script-from-history picks up the session code', async ({ page }) => {
  // The transcript *is* executable Python — typed input and the echo of GUI gestures. The button
  // merely concatenates them; this is the click → script → batch processing path.
  await runPython(page, 'app.layout.activate("windows")');
  await page.keyboard.press('Control+Shift+P');
  await page.locator('.palette input').fill('historique');
  await page.locator('.palette-item', { hasText: 'Nouveau script depuis' }).first().click();

  await expect(page.locator('.script-tab .monaco-editor')).toContainText('app.layout');
});

test('a recipe is assembled and runs as a single job', async ({ page }) => {
  // Ported from the old `container_panel`. What the test protects: the ordering, and the fact
  // that the recipe goes out as **one** job — not one per step.
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      + 'data = np.full((32, 32, 1), 0.25, dtype=np.float32)\n'
      + 'app.new_window(Image(data), window_id="Recette01")',
  );
  await runPython(
    page,
    'from retina.process.base import Process\n'
      + 'app.library["e2e-recette"] = __import__("retina").process.container.ProcessContainer(\n'
      + '    [Process.from_dict({"process_id": "Invert", "values": {}}),\n'
      + '     Process.from_dict({"process_id": "Invert", "values": {}})])',
  );

  await runPython(page, "app.layout.activate('library')");
  await page.locator('.sidebar .tree-row', { hasText: 'e2e-recette' }).dblclick();

  // Two steps, in the order the library returned them.
  const steps = page.locator('.tree-row', { hasText: 'Invert()' });
  await expect(steps).toHaveCount(2);

  await page.getByRole('button', { name: 'Exécuter sur la vue active' }).click();
  // Two inversions cancel out: the test looks at the number of history entries, which says there
  // really were two steps, and a single submission.
  await expect
    .poll(async () =>
      (
        await rpc<{ windows: { id: string; views: { history: { labels: string[] } }[] }[] }>(
          page,
          'state.snapshot',
        )
      ).windows.find((w) => w.id === 'Recette01')?.views[0]?.history.labels.length,
    )
    .toBe(3); // initial state + two steps
});

test('the file explorer opens an image from the server disk', async ({ page }) => {
  const folder = tempPath('retina-e2e-files');
  await runPython(
    page,
    'import os, shutil, numpy as np\n'
      + 'from retina.model.image import Image\n'
      + 'from retina.io.fits import save_fits\n'
      + `shutil.rmtree(${JSON.stringify(folder)}, ignore_errors=True)\n`
      + `os.makedirs(${JSON.stringify(folder)})\n`
      + 'data = np.full((16, 16, 1), 0.5, dtype=np.float32)\n'
      + `save_fits(${JSON.stringify(folder)} + "/cible.fits", Image(data))`,
  );

  await runPython(page, "app.layout.activate('files')");
  await page.getByTitle('Choisir un dossier de travail…').click();
  await answerPrompt(page, folder);

  const before = (await rpc<{ windows: unknown[] }>(page, 'state.snapshot')).windows.length;
  await page.locator('.sidebar .tree-row', { hasText: 'cible.fits' }).dblclick();
  await expect
    .poll(async () => (await rpc<{ windows: unknown[] }>(page, 'state.snapshot')).windows.length)
    .toBe(before + 1);
});

test('the shortcuts advertised by the palette are actually wired', async ({ page }) => {
  // The flaw script mode fixed: `Command.shortcut` was decorative, and the viewport keys
  // (+, −, 1, F) had no handler at all. Ctrl+J is the case verifiable without depending on an
  // open image.
  await runPython(page, "app.layout.show('console')");
  await expect(page.locator('.bottom')).toBeVisible();
  await page.locator('.workbench').click({ position: { x: 5, y: 5 } });
  await page.keyboard.press('Control+J');
  await expect(page.locator('.bottom')).toHaveCount(0);

  await page.keyboard.press('Control+J');
  await expect(page.locator('.bottom')).toBeVisible();
});

// --- Parity with professional astro suites -----------------------------------

test('a script error marks the offending line in the editor', async ({ page }) => {
  // Established suites print `…, line N` in their console and nothing takes you back to the
  // editor. Here the traceback sets a Monaco marker: this is a place where we go one better.
  await page.keyboard.press('Control+Shift+P');
  await page.locator('.palette input').fill('nouveau script');
  await page.locator('.palette-item').first().click();

  const editor = page.locator('.script-tab .monaco-editor');
  await expect(editor).toBeVisible();
  await editor.click();
  // An explicit Enter rather than `\n` inside `type`: Monaco does not turn it into a line break,
  // and the whole script would end up on a single line — which would test something else.
  await page.keyboard.type('a = 1');
  await page.keyboard.press('Enter');
  await page.keyboard.type('b = 2');
  await page.keyboard.press('Enter');
  await page.keyboard.type('c = a / 0');
  await page.keyboard.press('F5');

  // Monaco underlines the offending line: the trace of a successful `setModelMarkers`.
  await expect(page.locator('.script-tab .squiggly-error')).toHaveCount(1);
  // And the traceback is shown in red: IPython wrote it on stdout, hence in the colour of an
  // ordinary `print()` — a failing script looked like it had succeeded.
  await expect(page.locator('.bottom')).toContainText('ZeroDivisionError');
});

test('"Run file" goes through app.run_recipe', async ({ page }) => {
  // The echo announced `app.run_recipe(path)` while actually sending the buffer to the console:
  // the two gestures are now distinct, and each says what it does.
  const scriptPath = tempPath('retina-e2e-recette.py');
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      + `open(${JSON.stringify(scriptPath)}, "w").write(\n`
      + '    "import numpy as np\\n"\n'
      + '    "from retina.model.image import Image\\n"\n'
      + '    "app.new_window(Image(np.zeros((4, 4, 1), dtype=np.float32)), window_id=\'DepuisFichier\')\\n"\n'
      + ')',
  );

  const before = (await rpc<{ windows: unknown[] }>(page, 'state.snapshot')).windows.length;
  await rpc(page, 'app.run_recipe', { path: scriptPath });
  await expect
    .poll(async () => (await rpc<{ windows: unknown[] }>(page, 'state.snapshot')).windows.length)
    .toBe(before + 1);
});

test('a recipe step can be disabled without being lost', async ({ page }) => {
  // The classic gesture of established suites (`Purge disabled instances`): try the recipe
  // without one step.
  await runPython(page, 'app.library["e2e-drapeaux"] = __import__("retina").ProcessContainer([])');
  await runPython(
    page,
    'from retina.process.base import Process\n'
      + 'from retina.process.container import ProcessContainer\n'
      + 'pc = ProcessContainer([Process.from_dict({"process_id": "Invert", "values": {}}),\n'
      + '                       Process.from_dict({"process_id": "Rescale", "values": {}})])\n'
      + 'app.library["e2e-drapeaux"] = pc',
  );

  await runPython(page, "app.layout.activate('library')");
  await page.locator('.sidebar .tree-row', { hasText: 'e2e-drapeaux' }).dblclick();

  const checkboxes = page.locator('.container-tab input[type="checkbox"]');
  await expect(checkboxes).toHaveCount(2);
  await checkboxes.first().uncheck();
  // The step stays in the list — disabled, not removed: that is the whole difference.
  await expect(checkboxes).toHaveCount(2);
  await expect(page.locator('.container-tab').getByText('non enregistrée')).toBeVisible();
});

test('the source code of an instance opens as a script', async ({ page }) => {
  // Established suites put "Instance Source Code" on *every* process interface; here
  // `to_python_source` had existed from day one without a single interface calling it.
  await runPython(page, "app.layout.open_process('GaussianConvolution', {'sigma': 3.5})");
  await page.locator('.right-dock button[title^="Code source"]').click();
  await expect(page.locator('.script-tab .monaco-editor')).toContainText('GaussianConvolution');
});

/**
 * Clicks a point in **image** coordinates, on the viewport of the active window.
 *
 * Applies the real camera transform (`ViewportState.image_to_viewport`), read from the snapshot,
 * rather than assuming a zoom of 1 and perfect centering: opening a panel resizes the viewport,
 * and a `zoom_to_fit` triggered on the first pixel load applies after the test's `zoom_1_1`.
 * Assuming the geometry gave clicks off by a few percent — enough to skew a crop without making
 * it fail.
 */
async function imageToCanvas(page: Page, x: number, y: number): Promise<{ x: number; y: number }> {
  const snapshot = await rpc<{
    active_window: string | null;
    windows: Array<{ id: string; viewport: { zoom: number; center: [number, number] } }>;
  }>(page, 'state.snapshot');
  const vp = snapshot.windows.find((w) => w.id === snapshot.active_window)!.viewport;
  const box = (await page.locator('canvas:visible').first().boundingBox())!;
  return {
    x: box.x + (x - vp.center[0]) * vp.zoom + box.width / 2,
    y: box.y + (y - vp.center[1]) * vp.zoom + box.height / 2,
  };
}

/** Clicks a point in image coordinates. */
async function clickImagePoint(page: Page, x: number, y: number): Promise<void> {
  const point = await imageToCanvas(page, x, y);
  await page.mouse.click(point.x, point.y);
}

/**
 * Opens a process panel, **alone** in the right zone.
 *
 * The tests share one application, hence one layout: the forms opened by earlier tests stay put.
 * Two consequences, both seen for real — several "Apply" buttons make the selectors ambiguous,
 * and a dynamic tool left armed would grab the next test's clicks.
 */
async function openOnlyProcess(page: Page, processId: string): Promise<void> {
  await runPython(
    page,
    'for pid in list(app.layout.open_processes()):\n'
      + '    app.layout.close_process(pid)\n'
      + `app.layout.open_process(${JSON.stringify(processId)})`,
  );
}

/**
 * What the viewport actually renders — via a **screenshot**, not `gl.readPixels`.
 *
 * `readPixels` does not work here: the context is created without `preserveDrawingBuffer` (it
 * costs on *every* frame, see `renderer.renderLoupe`), so the browser clears the drawing buffer
 * after compositing. A read made even one frame later returns opaque black — indistinguishable
 * from a blank image, which would make the test pass for the wrong reason. The screenshot, on the
 * other hand, goes through the compositor, which holds the final image.
 *
 * The PNG is sent back into the page to be decoded by the browser (Node cannot read a PNG without
 * a dependency) then measured on a 2D canvas.
 */
async function readViewport(page: Page): Promise<{ max: number; center: number[] }> {
  // `:visible` is indispensable: dockview keeps inactive tabs in the DOM, and the tests have
  // several windows open (the image AND its mask). Without the filter we would measure the
  // mask window's viewport — which is precisely white where we expect black, hence a test that
  // fails while blaming the shader. The first visible canvas is the WebGL surface; the overlay
  // layer is its immediate sibling.
  const shot = await page.locator('canvas:visible').first().screenshot();
  return page.evaluate(async (base64: string) => {
    const image = new Image();
    image.src = `data:image/png;base64,${base64}`;
    await image.decode();
    const canvas = document.createElement('canvas');
    canvas.width = image.width;
    canvas.height = image.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('no 2D context to decode the screenshot');
    ctx.drawImage(image, 0, 0);
    const data = ctx.getImageData(0, 0, image.width, image.height).data;
    let max = 0;
    for (let i = 0; i < data.length; i += 4) {
      max = Math.max(max, data[i]!, data[i + 1]!, data[i + 2]!);
    }
    const middle = ((image.height >> 1) * image.width + (image.width >> 1)) * 4;
    return { max, center: [data[middle]!, data[middle + 1]!, data[middle + 2]!] };
  }, shot.toString('base64'));
}

/**
 * Creates a uniform bright image and attaches a mask of the same geometry to it.
 *
 * The mask is set from an `Image`, without opening a second window: `app.set_mask` accepts both.
 * One more mask window would make the measurement ambiguous — it is a second viewport, white
 * where we expect black.
 *
 * We do **not** close the windows left by earlier tests. The tests share a single `Application`
 * (workers: 1), but closing a window while a client is still mounting it triggers a
 * `set_viewport` towards a window that no longer exists — an unavoidable race, and `afterEach`
 * forbids any console error. Each test therefore creates a window with a unique id, which becomes
 * the active tab; `:visible` is what disambiguates on the measurement side.
 */
async function withMask(page: Page, id: string, maskExpression: string): Promise<void> {
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      + 'data = np.full((200, 300, 3), 0.8, dtype=np.float32)\n'
      + `app.new_window(Image(data), window_id='${id}')\n`
      + `app.set_mask(Image(${maskExpression}))\n`
      + 'app.set_stf_enabled(False)\n'   // raw pixels: the threshold must stay readable
      + 'app.zoom_to_fit()',
  );
}

test('a visible mask really composites pixels, and can be hidden', async ({ page }) => {
  // An all-black mask = everything is protected. This is the case where the display must be the
  // most spectacular, hence the one that proves the shader really samples the second texture.
  await withMask(page, 'MasqueVu', 'np.zeros((200, 300, 1), dtype=np.float32)');
  await runPython(page, "app.set_mask_display_mode(retina.MaskDisplayMode.MULTIPLY)");

  // The center rather than the maximum: the overlay layer draws on top (preview frames,
  // crosshairs) and the screenshot includes it — the maximum would measure that chrome.
  const off = await readViewport(page);
  expect(Math.max(...off.center)).toBeLessThan(40);

  // Hiding the mask does not touch the pixels, only the rendering.
  await page.locator('.status-bar button[title*="Cacher le masque"]').click();
  await expect(page.locator('.status-bar .codicon-eye-closed')).toBeVisible();
  const hidden = await readViewport(page);
  expect(Math.min(...hidden.center)).toBeGreaterThan(150);
});

test('overlay mode tints the PROTECTED area, not the processed one', async ({ page }) => {
  // The direction an eyeball test never catches: both images are plausible. A black mask
  // (everything protected) + red overlay ⇒ the whole image must turn pure red.
  await withMask(page, 'MasqueTeinte', 'np.zeros((200, 300, 1), dtype=np.float32)');
  await runPython(page, "app.set_mask_display_mode(retina.MaskDisplayMode.OVERLAY_RED)");

  const protectedArea = await readViewport(page);
  const [r, g, b] = protectedArea.center as [number, number, number];
  expect(r).toBeGreaterThan(200);
  expect(g).toBeLessThan(40);
  expect(b).toBeLessThan(40);

  // White mask: everything is processed, so nothing is tinted — the image passes through intact.
  await runPython(page, 'app.set_mask(Image(np.ones((200, 300, 1), dtype=np.float32)))');
  const processed = await readViewport(page);
  const [r2, g2, b2] = processed.center as [number, number, number];
  expect(Math.abs(r2 - g2)).toBeLessThan(12);
  expect(Math.abs(g2 - b2)).toBeLessThan(12);
  expect(r2).toBeGreaterThan(150);
});

test('on a preview, the mask is read at the right place in the window', async ({ page }) => {
  // The trap here: the mask covers the window, while the displayed texture is only a piece of it.
  // Without a uv transform, the whole mask would be squeezed into the preview — and the white
  // half would show up inside a preview that is entirely protected.
  // White mask over the first two thirds (x < 200), black afterwards. The proportions are not
  // arbitrary: with the cut in the middle, the center of a badly transformed preview would land
  // exactly on the boundary, and the test would settle nothing.
  await withMask(
    page,
    'MasquePreview',
    'np.concatenate([np.ones((200, 200, 1), dtype=np.float32),'
      + ' np.zeros((200, 100, 1), dtype=np.float32)], axis=1)',
  );
  await runPython(page, "app.set_mask_display_mode(retina.MaskDisplayMode.MULTIPLY)");

  // A preview entirely inside the last third, the one the mask protects (black).
  await runPython(page, "app.select_view(app.new_preview(210, 20, 290, 180, 'Zone').id)");
  await runPython(page, 'app.zoom_to_fit()');

  const preview = await readViewport(page);
  // Multiplied by a mask that is zero over this whole area: the center must be dark. An
  // untransformed uv would read the mask at the middle of the *window* (x = 150), hence white,
  // hence a preview displayed intact although it is entirely protected.
  expect(Math.max(...preview.center)).toBeLessThan(40);
});

test('clicking the image places a DBE sample, and draws it', async ({ page }) => {
  // The gesture the `dynamic` mode promised without ever delivering: it existed on the domain
  // side and no client code listened to it, so that "Place samples" armed a mode where clicking
  // did nothing. This is the foundation of all four dynamic tools.
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      // A same-named window left over by an earlier run would make the server-side pixel
      // generation key alternate between two arrays, and the client could no longer request a
      // valid generation: 409s on a loop. `app.new_window` does not enforce unique ids.
      + 'for w in list(app.windows): app.close_window(w)\n'
      + "app.new_window(Image(np.full((200, 300, 3), 0.3, dtype=np.float32)), window_id='Dbe')\n"
      + 'app.zoom_to_fit()',
  );
  await openOnlyProcess(page, 'DynamicBackgroundExtraction');

  const canvas = page.locator('canvas:visible').first();
  await page.getByRole('button', { name: 'Placer des échantillons' }).click();
  // The interaction mode really went through the domain — the GUI has no state of its own.
  await expect
    .poll(async () => {
      const snapshot = await rpc<{ windows: Array<{ id: string; viewport: { interaction_mode: string } }> }>(
        page, 'state.snapshot',
      );
      return snapshot.windows.find((w) => w.id === 'Dbe')?.viewport.interaction_mode;
    })
    .toBe('dynamic');

  const box = (await canvas.boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.4, box.y + box.height * 0.4);
  await page.mouse.click(box.x + box.width * 0.6, box.y + box.height * 0.6);

  // The panel counter: the two clicks did fill the form parameter.
  await expect(page.locator('.right-dock')).toContainText('2 échantillons');

  // And the markers made it up to the domain, hence are visible from the console too.
  // Polled: the panel republishes its markers through an unawaited RPC on every change, and the
  // click is acknowledged by the form before the overlay has completed its round trip.
  type Overlay = { kind: string; tag?: string; points?: number[][] };
  await expect
    .poll(async () => {
      const snapshot = await rpc<{
        windows: Array<{ id: string; viewport: { overlays: Overlay[] } }>;
      }>(page, 'state.snapshot');
      const placed = snapshot.windows.find((w) => w.id === 'Dbe')?.viewport.overlays ?? [];
      return placed.map((o) => `${o.kind}:${o.tag ?? ''}:${o.points?.length ?? 0}`).join(' ');
    })
    .toBe('markers:dbe:2');
});

test('the status bar shows RA/Dec on a plate-solved image', async ({ page }) => {
  // `viewport_to_celestial` had always existed in the domain without any RPC exposing it: on a
  // plate-solved image, the interface could not say where you were looking.
  await runPython(
    page,
    'import numpy as np\n'
      + 'from astropy.wcs import WCS\n'
      + 'from retina.model.image import Image\n'
      + 'for w in list(app.windows): app.close_window(w)\n'
      + "win = app.new_window(Image(np.full((100, 200, 3), 0.5, dtype=np.float32)), window_id='Wcs')\n"
      + 'wcs = WCS(naxis=2)\n'
      + 'wcs.wcs.crpix = [100, 50]\n'
      + 'wcs.wcs.crval = [10.0, 41.0]\n'
      + 'wcs.wcs.cdelt = [-1/3600, 1/3600]\n'
      + "wcs.wcs.ctype = ['RA---TAN', 'DEC--TAN']\n"
      + 'win.wcs = wcs\n'
      + 'app.zoom_to_fit()',
  );

  const canvas = page.locator('canvas:visible').first();
  const box = (await canvas.boundingBox())!;
  // The readout fires on hover, in `readout` mode (the domain default).
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.move(box.x + box.width / 2 + 3, box.y + box.height / 2 + 2);

  // α and δ formatted in sexagesimal. The field is centered on 10° = 00h40m, +41°; we do not
  // pin the seconds down, as they depend on the exact pixel under the cursor.
  await expect(page.locator('.status-bar')).toContainText(/α 00h(39|40)m/);
  await expect(page.locator('.status-bar')).toContainText(/δ \+41°/);
});

test('a preview can be renamed, frozen and deleted from the right-click menu', async ({ page }) => {
  // `rename_preview`, `store_preview` and `delete_preview` had been served and echoed from day
  // one without any gesture leading to them: you created a preview with the mouse and needed the
  // console to get rid of it.
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      + 'for w in list(app.windows): app.close_window(w)\n'
      + "app.new_window(Image(np.full((100, 200, 3), 0.5, dtype=np.float32)), window_id='Prev')\n"
      // A distinctive name: the tests share the application, and a same-named preview left by
      // another test would make the selector ambiguous (Playwright refuses two targets).
      + "app.new_preview(10, 10, 90, 60, 'ZoneCtx')",
  );

  await page.locator('.activity-item[title*="Fenêtres"]').click();
  const row = page.locator('.sidebar .tree-row', { hasText: 'ZoneCtx' });
  await expect(row).toBeVisible();

  // Rename
  await row.click({ button: 'right' });
  await page.locator('.context-menu-item', { hasText: 'Renommer' }).click();
  await answerPrompt(page, 'CoinCtx');
  await expect(page.locator('.sidebar .tree-row', { hasText: 'CoinCtx' })).toBeVisible();

  // Freeze: ⚡ (volatile) becomes 🔒
  const renamed = page.locator('.sidebar .tree-row', { hasText: 'CoinCtx' });
  await expect(renamed).toContainText('⚡');
  await renamed.click({ button: 'right' });
  await page.locator('.context-menu-item', { hasText: 'Figer' }).click();
  await expect(page.locator('.sidebar .tree-row', { hasText: 'CoinCtx' })).toContainText('🔒');

  // Delete — and the domain has no trace of it left, not merely the tree.
  await page.locator('.sidebar .tree-row', { hasText: 'CoinCtx' }).click({ button: 'right' });
  await page.locator('.context-menu-item', { hasText: 'Supprimer' }).click();
  await expect
    .poll(async () => {
      const snapshot = await rpc<{ windows: Array<{ id: string; views: Array<{ id: string }> }> }>(
        page, 'state.snapshot',
      );
      return snapshot.windows.find((w) => w.id === 'Prev')?.views.map((v) => v.id) ?? [];
    })
    .toEqual(['Prev']);
});

test('a crop drawn with the mouse cuts out the right area', async ({ page }) => {
  // `DynamicCrop` had had its core for a long time and no gesture at all: you had to type
  // fractions into a form to crop an image you had right in front of you.
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      // All windows, not merely the same-named ones: the tests share one application, and
      // accumulating tabs makes the `canvas:visible` selectors ambiguous. (The WebGL context
      // ceiling, for its part, is gone — shared context.)
      + 'for w in list(app.windows): app.close_window(w)\n'
      + "app.new_window(Image(np.full((100, 200, 3), 0.6, dtype=np.float32)), window_id='Crop')\n"
      // Zoom 1:1: one canvas pixel is then one image pixel, which makes the gesture directly
      // verifiable in dimensions rather than through a conversion.
      + 'app.zoom_1_1()',
  );
  await openOnlyProcess(page, 'DynamicCrop');
  // Tools are armed explicitly: an open panel does not seize the pointer.
  await page.getByRole('checkbox', { name: 'Ajuster sur l’image' }).check();

  // The default frame covers everything: the first drag must therefore *draw*, not move.
  const start = await imageToCanvas(page, 70, 35);
  const end = await imageToCanvas(page, 130, 65);
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 8 });
  await page.mouse.up();

  // What the panel announces and what the process delivers must match: this is where the
  // gesture, the form fractions and the cut-out meet. We read the announcement rather than
  // hardcoding it — the screen→image conversion depends on the exact viewport geometry.
  const reported = await page
    .locator('.right-dock')
    .getByText(/^\d+ × \d+ px$/)
    .innerText();
  const [width, height] = reported.match(/\d+/g)!.map(Number);
  expect(width).toBeGreaterThan(40);
  expect(width).toBeLessThan(80);
  expect(height).toBeGreaterThan(20);
  expect(height).toBeLessThan(45);

  await page.getByRole('button', { name: 'Appliquer', exact: true }).click();
  await expect
    .poll(async () => {
      const snapshot = await rpc<{
        windows: Array<{ id: string; views: Array<{ width: number; height: number }> }>;
      }>(page, 'state.snapshot');
      const view = snapshot.windows.find((w) => w.id === 'Crop')?.views[0];
      return view ? `${view.width}×${view.height}` : '';
    })
    .toBe(`${width}×${height}`);
});

test('two clone stamps go out as a single job, in order', async ({ page }) => {
  // The core only carries one stamp per instance; the panel stacks them and plays the lot as one
  // `run_container` — one job, one echo, a guaranteed order. The container does, however, push a
  // history entry **per step**: each stamp remains separately undoable.
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      + 'for w in list(app.windows): app.close_window(w)\n'
      + 'data = np.zeros((100, 200, 3), dtype=np.float32)\n'
      + 'data[10:40, 10:40, :] = 0.9\n'   // a bright blob to copy
      + "app.new_window(Image(data), window_id='Tampon')\n"
      + 'app.zoom_1_1()',
  );
  await openOnlyProcess(page, 'CloneStamp');
  await page.getByRole('checkbox', { name: 'Tamponner sur l’image' }).check();

  for (const target of [[150, 25], [150, 70]] as Array<[number, number]>) {
    await clickImagePoint(page, 25, 25);
    await clickImagePoint(page, target[0], target[1]);
  }
  await expect(page.locator('.right-dock')).toContainText('Appliquer 2 tampons');

  await page.getByRole('button', { name: /Appliquer 2 tampons/ }).click();

  // Both steps are in the history (along with `initial`), and the pixels really are laid down at
  // both destinations.
  await expect
    .poll(async () => {
      const snapshot = await rpc<{
        windows: Array<{ id: string; views: Array<{ history: { labels: string[] } }> }>;
      }>(page, 'state.snapshot');
      return snapshot.windows.find((w) => w.id === 'Tampon')?.views[0]?.history.labels ?? [];
    })
    .toEqual(['initial', 'CloneStamp', 'CloneStamp']);

  const bright1 = await rpc<{ channels: Array<{ mean: number }> } | null>(page, 'app.readout', {
    x: 150, y: 25, window: 'Tampon',
  });
  const bright2 = await rpc<{ channels: Array<{ mean: number }> } | null>(page, 'app.readout', {
    x: 150, y: 70, window: 'Tampon',
  });
  expect(bright1?.channels[0]?.mean ?? 0).toBeGreaterThan(0.5);
  expect(bright2?.channels[0]?.mean ?? 0).toBeGreaterThan(0.5);
});

test('DynamicPSF measures the stars, lists them and draws them', async ({ page }) => {
  // Two things get checked here. The per-star detail makes it all the way to the client — it
  // could not: `JobRunner` only picked up `job.result` for the pipeline, so a measurement process
  // launched from a form returned nothing. And clicking a star goes through the `positions`
  // parameter, so it stays scriptable.
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      + 'for w in list(app.windows): app.close_window(w)\n'
      + 'rng = np.random.default_rng(5)\n'
      + 'champ = (rng.random((120, 200)) * 0.002).astype(np.float32)\n'
      + 'ys, xs = np.mgrid[0:120, 0:200]\n'
      + 'for cx, cy in [(50, 40), (140, 40), (100, 90)]:\n'
      + '    champ += (0.8 * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * 1.7 ** 2)))).astype(np.float32)\n'
      + "app.new_window(Image(np.clip(champ, 0, 1)[:, :, None]), window_id='Psf')\n"
      + 'app.zoom_1_1()',
  );
  await openOnlyProcess(page, 'DynamicPSF');

  await page.getByRole('button', { name: 'Détecter' }).click();

  // The table fills up: the measurement crossed the network all the way to the interface.
  await expect(page.locator('.right-dock')).toContainText(/[23] étoiles/);
  await expect(page.locator('.right-dock table tbody tr').first()).toBeVisible();

  // And the fitted ellipses are placed in the domain — hence visible from the console.
  await expect
    .poll(async () => {
      const snapshot = await rpc<{
        windows: Array<{ id: string; viewport: { overlays: Array<{ kind: string; tag?: string; items?: unknown[] }> } }>;
      }>(page, 'state.snapshot');
      const placed = snapshot.windows.find((w) => w.id === 'Psf')?.viewport.overlays ?? [];
      const ellipses = placed.find((o) => o.tag === 'dynamicpsf');
      return `${ellipses?.kind ?? 'rien'}:${ellipses?.items?.length ?? 0}`;
    })
    .toMatch(/^ellipses:[23]$/);

  // This process does not touch the pixels: no history entry must appear.
  const snapshot = await rpc<{
    windows: Array<{ id: string; views: Array<{ history: { labels: string[] } }> }>;
  }>(page, 'state.snapshot');
  expect(snapshot.windows.find((w) => w.id === 'Psf')?.views[0]?.history.labels).toEqual(['initial']);
});

test('manual alignment pairs points across two views', async ({ page }) => {
  // The gesture crosses two viewports, which moves the active window along the way. Two traps
  // follow, both checked here: the tool must route through the **clicked** view (not the active
  // one), and the application must explicitly target the source view — otherwise we register the
  // image that serves as the model.
  await runPython(
    page,
    'import numpy as np\n'
      + 'from retina.model.image import Image\n'
      + 'for w in list(app.windows): app.close_window(w)\n'
      + 'a = np.zeros((80, 100, 1), dtype=np.float32); a[16:25, 16:25, 0] = 0.9\n'
      + 'b = np.zeros((90, 120, 1), dtype=np.float32); b[26:35, 36:45, 0] = 0.9\n'
      // Two different geometries: after registration, A must take B's, which proves that
      // `reference` really was filled in by the gesture.
      + "app.new_window(Image(b), window_id='AlignB')\n"
      + "cible = app.new_window(Image(a), window_id='AlignA')\n"
      + 'app.set_active_window(cible)\n'
      + 'app.zoom_1_1()',
  );
  await openOnlyProcess(page, 'DynamicAlignment');
  await page.getByRole('checkbox', { name: 'Poser des paires' }).check();

  /**
   * Clicks an image point on the designated window, after waiting for it to actually be on
   * screen. The tab switch follows the snapshot: clicking without waiting would still target the
   * previous viewport, with the other image's geometry — wrong yet plausible pairs.
   */
  /**
   * Activates a window and clicks an image point in it.
   *
   * The viewport is **set explicitly** before every click. Without that, the client camera and
   * the snapshot can diverge for an instant: a freshly mounted panel runs its own `zoom_to_fit`
   * on the first pixel load, and the commit that follows arrives later. We then computed the
   * screen position from a state the client had not yet adopted, and the recorded point landed
   * hundreds of pixels away from the target — visible in the pair list, invisible in the result,
   * which remains a plausible registration.
   */
  const pointer = async (windowId: string, imageX: number, imageY: number) => {
    const geometry: Record<string, [number, number]> = { AlignA: [100, 80], AlignB: [120, 90] };
    const [w, h] = geometry[windowId]!;
    await runPython(
      page,
      `app.set_active_window(app.view('${windowId}').window)\n`
        + `app.set_viewport((${w / 2}, ${h / 2}), zoom=1.0)`,
    );
    await expect(page.locator('.status-bar')).toContainText(windowId);
    // The zoom only appears in the bar once the viewport has been hovered (the state comes from
    // a pointer move). That hover therefore acts as a synchronization point: when the bar shows
    // 100 %, the client camera has indeed adopted the viewport we just set.
    const center = (await page.locator('canvas:visible').first().boundingBox())!;
    await page.mouse.move(center.x + center.width / 2, center.y + center.height / 2);
    await expect(page.locator('.status-bar')).toContainText('100 %');
    await clickImagePoint(page, imageX, imageY);
  };

  // Three pairs, offset by (+20, +10) — the translation that maps A onto B.
  const marks: Array<[number, number]> = [[20, 20], [60, 30], [40, 60]];
  for (const [x, y] of marks) {
    await pointer('AlignA', x, y);
    await pointer('AlignB', x + 20, y + 10);
  }

  await expect(page.locator('.right-dock')).toContainText('3 paires');
  await expect(page.locator('.right-dock')).toContainText('référence : AlignB');

  // The active view here is AlignB: the panel button must nevertheless register AlignA.
  await page.getByRole('button', { name: /Recaler AlignA/ }).click();

  await expect
    .poll(async () => {
      const snapshot = await rpc<{
        windows: Array<{ id: string; views: Array<{ width: number; height: number }> }>;
      }>(page, 'state.snapshot');
      const view = snapshot.windows.find((w) => w.id === 'AlignA')?.views[0];
      return view ? `${view.width}×${view.height}` : '';
    })
    .toBe('120×90');

  // And the blob did migrate to the place it occupies in the reference. Polled: the geometry
  // appears in the snapshot before the probe sees the new pixels, and asserting without waiting
  // read the previous image — 0 where we expect 0.9.
  await expect
    .poll(async () => {
      const probe = await rpc<{ channels: Array<{ mean: number }> } | null>(page, 'app.readout', {
        x: 40, y: 30, window: 'AlignA',
      });
      return probe?.channels[0]?.mean ?? 0;
    })
    .toBeGreaterThan(0.5);
});

test('annotation is laid down as an overlay without touching the pixels', async ({ page }) => {
  // `Annotation` used to burn its grid into the image: the values under the lines were lost for
  // any later measurement. Overlay mode is now the default; "flatten" remains available through
  // `render_mode='pixels'`.
  await runPython(
    page,
    'import numpy as np\n'
      + 'from astropy.wcs import WCS\n'
      + 'from retina.model.image import Image\n'
      + 'for w in list(app.windows): app.close_window(w)\n'
      + "win = app.new_window(Image(np.full((120, 160, 1), 0.4, dtype=np.float32)), window_id='Annot')\n"
      + 'wcs = WCS(naxis=2)\n'
      + 'wcs.wcs.crpix = [80, 60]\n'
      + 'wcs.wcs.crval = [10.0, 41.0]\n'
      + 'wcs.wcs.cdelt = [-10/3600, 10/3600]\n'
      + "wcs.wcs.ctype = ['RA---TAN', 'DEC--TAN']\n"
      + 'win.wcs = wcs\n'
      + 'app.zoom_to_fit()',
  );

  await rpc(page, 'process.run', {
    process_id: 'Annotation',
    params: { grid_spacing: 0.1, line_width: 0.02, render_mode: 'overlay' },
    view: 'Annot',
  });

  await expect
    .poll(async () => {
      const snapshot = await rpc<{
        windows: Array<{
          id: string;
          views: Array<{ history: { labels: string[] } }>;
          viewport: { overlays: Array<{ kind: string; tag?: string }> };
        }>;
      }>(page, 'state.snapshot');
      const win = snapshot.windows.find((w) => w.id === 'Annot');
      const grid = (win?.viewport.overlays ?? []).filter((o) => o.tag === 'annotation');
      // Polylines laid down, and a history left untouched: nothing was burned in.
      return `${grid.map((o) => o.kind).join('+')}|${win?.views[0]?.history.labels.join(',')}`;
    })
    .toMatch(/^lines(\+text)?\|initial$/);
});

test('a file dragged from the explorer onto the viewport opens', async ({ page }) => {
  // The gesture of the established astro suites — and of VS Code: you drag a file to where you
  // are looking, and it opens. `app.open` underneath, hence echoed like a double-click or a line
  // typed in the console.
  const folder = tempPath('retina-e2e-drag');
  await runPython(
    page,
    'import os, shutil, numpy as np\n'
      + 'from retina.model.image import Image\n'
      + 'from retina.io.fits import save_fits\n'
      + `shutil.rmtree(${JSON.stringify(folder)}, ignore_errors=True)\n`
      + `os.makedirs(${JSON.stringify(folder)})\n`
      + 'data = np.full((16, 16, 1), 0.5, dtype=np.float32)\n'
      + `save_fits(${JSON.stringify(folder)} + "/glissee.fits", Image(data))\n`
      // An already-open image: without a viewport on screen, there is nowhere to drop.
      + 'app.new_window(Image(data), window_id="Accueil")',
  );

  await runPython(page, "app.layout.activate('files')");
  await page.getByTitle('Choisir un dossier de travail…').click();
  await answerPrompt(page, folder);

  const source = page.locator('.sidebar .tree-row', { hasText: 'glissee.fits' });
  await expect(source).toHaveAttribute('draggable', 'true');

  const before = (await rpc<{ windows: unknown[] }>(page, 'state.snapshot')).windows.length;
  await source.dragTo(page.locator('canvas').first());
  await expect
    .poll(async () => (await rpc<{ windows: unknown[] }>(page, 'state.snapshot')).windows.length)
    .toBe(before + 1);
});
