import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { defineConfig } from '@playwright/test';

const ROOT = resolve(process.cwd(), '..');
const CONFIG_DIR = resolve(ROOT, 'web', '.e2e-config');

/**
 * Turns the **guided tour** off before the first test.
 *
 * `session.show_tour` defaults to `True` (cf. `python/retina/preferences.py`), and the run's
 * config directory is brand new: the tour therefore opened on every launch. It overlays the
 * workbench and **intercepts clicks** — Playwright then refused to act ("subtree intercepts
 * pointer events") and a dozen scenarios timed out on buttons that were perfectly present, for
 * a reason that only showed up in the call log.
 *
 * It is written here rather than closed inside a test: the run must start from a deterministic
 * state, just like the language pinned below. Only this key is set — `preferences.json`
 * contains nothing but the non-default, and the rest keeps its normal values.
 */
mkdirSync(CONFIG_DIR, { recursive: true });
writeFileSync(
  resolve(CONFIG_DIR, 'preferences.json'),
  JSON.stringify({ version: 1, values: { 'session.show_tour': false } }, null, 2),
  'utf8',
);

/**
 * The venv interpreter, as an absolute path.
 *
 * A relative path starting with `../` cannot be resolved as a command by `cmd.exe` — Playwright
 * hands the line to the system shell, not to a portable executor.
 */
const PYTHON = [
  resolve(ROOT, '.venv', 'Scripts', 'python.exe'), // Windows
  resolve(ROOT, '.venv', 'bin', 'python'), // POSIX
].find(existsSync) ?? 'python';

// The E2E smoke test functionally replaces `scripts/gui_smoke.py` for the web shell: it does not
// check pixel-perfect rendering, but the **wiring** frontend ↔ server ↔ domain.
//
// Fixed token: Playwright must know the URL before launching the server, yet the server normally
// draws a random token at startup. Hence `--token`, explicitly reserved for the tests.
//
// `RETINA_CONFIG_DIR` isolates the config: a test must not write into the real library or the
// real perspectives. Same precaution as `scripts/gui_smoke.py`.

const PORT = 8799;
const TOKEN = 'playwright-e2e';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false, // one server, hence one `app`: the tests would step on each other
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    // The WebGL2 viewport runs in software under Playwright's CI: enough to check that pixels
    // arrive, not to measure performance.
    launchOptions: { args: ['--enable-unsafe-swiftshader'] },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `"${PYTHON}" -m retina.web --no-shell --port ${PORT} --token ${TOKEN}`,
    url: `http://127.0.0.1:${PORT}/api/ping`,
    reuseExistingServer: false,
    timeout: 60_000,
    cwd: ROOT,
    env: {
      RETINA_CONFIG_DIR: CONFIG_DIR,
      // **Pinned** language. Without it, the suite would pass or fail depending on the machine's
      // `LANG`, since the server serves the system locale and the frontend adopts it.
      // French is chosen because that is what the existing scenarios assert; `i18n.spec.ts` is
      // the only one to break free of it, and it does so explicitly.
      RETINA_LANGUAGE: 'fr',
    },
  },
});

export { PORT, TOKEN };
