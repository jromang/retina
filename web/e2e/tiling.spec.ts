// Tiling of large images — tested WITHOUT a giant image.
//
// The `localStorage['retina.debug.textureCap']` override forces an artificially low texture
// cap (256 px), read by `tileCap()` only: a synthetic 600×400 image then takes exactly the
// tiled path (overview + tiles) that a 30k frame would take under the real cap — decimated
// overview, tiles fetched with `?scale=&rect=`, multi-quad rendering. Creating a real 20k
// image here would cost minutes of CI to exercise the same code.

import { expect, test, type Page } from '@playwright/test';

const TOKEN = 'playwright-e2e';

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

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
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

  // The debug cap must be set BEFORE the application loads its pixels.
  await page.addInitScript(() => {
    localStorage.setItem('retina.debug.textureCap', '256');
  });
  await page.goto(`/?t=${TOKEN}`);
  await page.locator('.workbench').waitFor({ state: 'visible' });

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
  await runPython(
    page,
    'for w in list(app.windows):\n'
    + "    if w.id == 'Pave':\n"
    + '        app.close_window(w)\n',
  );
});

/** RGB sum of a 10×10 square at the centre of the first visible display canvas. */
async function centerSum(page: Page): Promise<number> {
  return page.evaluate(async () => {
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const canvas = [...document.querySelectorAll('canvas')].find((c) => c.clientWidth > 0);
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return -1;
    const pixels = ctx.getImageData(
      Math.floor(canvas.width / 2) - 5, Math.floor(canvas.height / 2) - 5, 10, 10,
    ).data;
    let sum = 0;
    for (let i = 0; i < pixels.length; i += 4) sum += pixels[i]! + pixels[i + 1]! + pixels[i + 2]!;
    return sum;
  });
}

test('an image beyond the texture cap is rendered through tiling', async ({ page }) => {
  // 600×400 > the 256 cap: tiled path. A full-field gradient, bright after auto-stretch.
  await runPython(
    page,
    'import numpy as np\n'
    + 'from retina.model.image import Image\n'
    + 'y, x = np.mgrid[0:400, 0:600].astype(np.float32)\n'
    + 'data = np.stack([x / 600 * 0.5 + 0.2] * 3, axis=-1).astype(np.float32)\n'
    + "app.new_window(Image(data), window_id='Pave')\n"
    + 'app.compute_auto_stf()',
  );

  // The overview arrives, the mosaic is drawn: non-zero pixels at the centre.
  await expect.poll(() => centerSum(page), { timeout: 15_000 }).toBeGreaterThan(0);

  // Zoom 1:1 (full-resolution level → tiles) then pan: still pixels, zero console error (the
  // afterEach makes sure of it) — this is the path that used to raise before tiling.
  await rpc(page, 'app.zoom_1_1', {});
  await expect.poll(() => centerSum(page), { timeout: 15_000 }).toBeGreaterThan(0);
  await rpc(page, 'app.set_zoom', { zoom: 0.5 });
  await expect.poll(() => centerSum(page), { timeout: 15_000 }).toBeGreaterThan(0);
});
