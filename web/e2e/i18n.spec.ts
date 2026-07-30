// Interface language, end to end.
//
// The one place where the three moving parts are checked together: resolution on the client
// side (`shell/locale.ts`), the preference persisted in the domain (`retina.session`), and
// the reload that reconciles them. None of the three can be tested convincingly on its own —
// the bug we fear is precisely at the seam.
//
// # The scenario that matters
//
// Change the language **from the console**, and check that the interface follows. This is
// pillar #2 of ARCHITECTURE.md put to the test: if `app.set_language("en")` typed in the
// console does not rename the menus, then the GUI has a power of its own, which it must never
// have.
//
// The server is pinned to French by `playwright.config.ts` (`RETINA_LANGUAGE=fr`), which makes
// the other scenarios deterministic. So this file works *against* that pinning: it sets an
// explicit preference, which takes priority over the environment variable… except that it does
// not — the resolution order puts `RETINA_LANGUAGE` **before** the preference, and that is
// deliberate (it is the only lever available without an interface). The tests below account for
// it: they check what the preference writes and what the client makes of it, not that it wins
// over a CI pinning.

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
  await page.goto(`/?t=${TOKEN}`);
  await page.locator('.workbench').waitFor({ state: 'visible' });

  // Test RPC bridge: a parallel WebSocket, talking to the same server hence to the same `app`.
  // Copied from `smoke.spec.ts` rather than shared: Playwright does not load a common module
  // across specs without a dedicated fixture, and a fixture for twenty lines would cost more
  // than the repetition.
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
  // Put the preference back to "automatic": it lives in the `session.json` of the e2e config,
  // so it would survive into the next scenario.
  await runPython(page, 'app.set_language(None)');
});

test('the language preference goes through the domain, and comes back in the session state',
  async ({ page }) => {
    // Starting point: no explicit preference, the effective language comes from the environment.
    const before = await rpc<{ language: string | null; effective_language: string }>(
      page, 'project.recent');
    expect(before.language).toBeNull();
    expect(before.effective_language).toBe('fr');

    // The user's gesture, written in Python — this is the parity test.
    await runPython(page, 'app.set_language("en")');

    const after = await rpc<{ language: string | null }>(page, 'project.recent');
    expect(after.language).toBe('en');
    // `effective_language` stays "fr": `RETINA_LANGUAGE` wins over the preference, and that is
    // intended. What the test checks is that the choice is properly **recorded**.
  });

test('an unavailable language is refused, and the previous one stays in place',
  async ({ page }) => {
    await runPython(page, 'app.set_language("fr")');

    const refusal = await rpc<{ error?: { message: string } }>(page, 'console.execute', {
      code: 'app.set_language("klingon")',
    });
    // The console returns the Python error rather than raising it on the RPC side.
    expect(JSON.stringify(refusal)).toContain('langue inconnue');

    const state = await rpc<{ language: string | null }>(page, 'project.recent');
    expect(state.language).toBe('fr');
  });

test('the interface renders in the server language, `lang` attribute included',
  async ({ page }) => {
    // `RETINA_LANGUAGE=fr` on the server side: the client must have adopted French, whatever
    // its initial guess was (empty mirror, `navigator.language` of the test browser, which is
    // in English).
    await expect(page.locator('html')).toHaveAttribute('lang', 'fr');

    const menus = await page.locator('.menubar-item').allInnerTexts();
    expect(menus).toContain('Fichier');
    expect(menus).toContain('Aide');
  });

test('parameter labels come from the server, hence in the same language',
  async ({ page }) => {
    // The seam that is easiest to miss: forms are generated from `process.list`, translated on
    // the Python side, whereas the rest of the interface is translated on the client side. Both
    // must speak the same language.
    const processes = await rpc<Array<{ process_id: string; parameters: Array<{ id: string; label: string }> }>>(
      page, 'process.list');
    const calibration = processes.find((p) => p.process_id === 'ImageCalibration');
    expect(calibration, 'ImageCalibration missing from the catalogue').toBeTruthy();

    // A precise label rather than an accent probe: `dark_scale` has an English msgid
    // ("Dark scale") and a distinct French translation, so the assertion fails just as well
    // when the translation is missing as when the server serves the wrong language.
    const scale = calibration!.parameters.find((p) => p.id === 'dark_scale');
    expect(scale?.label).toBe('Échelle du dark');
  });

test('the documentation follows the interface language', async ({ page }) => {
  // The hole found while writing this: `?lang=` had always been served and the frontend never
  // sent it, so the documentation stayed in the default language.
  //
  // The assertion is on the **standfirst**, not on the title: ever since the index hosts the
  // guides, it is called "Documentation" in both languages, which would no longer prove
  // anything.
  const response = await page.request.get(`/api/doc/?t=${TOKEN}&lang=fr`);
  expect(response.ok()).toBeTruthy();
  const french = await response.text();
  expect(french).toContain('Commencez par un guide');
  expect(french).toContain('Guides');

  const english = await page.request.get(`/api/doc/?t=${TOKEN}&lang=en`);
  expect(await english.text()).toContain('Start with a guide');
});
