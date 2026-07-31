// From `vitest/config`, not `vite`: the `test` block below is not part of Vite's own config
// type. Vitest 3 augmented it globally, which made the plain `vite` import work by accident;
// TypeScript 7 rejects the excess property that TypeScript 5 let through on the overload.
import { defineConfig } from 'vitest/config';
import preact from '@preact/preset-vite';
import { paraglideVitePlugin } from '@inlang/paraglide-js';

// The build feeds the Python package directly: `resources/webui/` is served by aiohttp in
// production and embedded in the wheel by maturin (`include = resources/**`). The directory is
// gitignored — it is an artifact, the source lives here.
//
// In development, Vite serves the page (HMR) and proxies `/api` + `/ws` to the Python server:
// the native window pointed at :5173 therefore talks to the real domain, with no intermediate
// build.
export default defineConfig({
  plugins: [
    preact(),
    // Paraglide *compiles* the `messages/{en,fr}.json` catalogs into tree-shakable `m.key()`
    // functions: no catalog loaded at runtime, and a missing key becomes a `tsc` error, which
    // does half the work of the hard-coded-string guard.
    //
    // `emitTsDeclarations` is not cosmetic: the output is JavaScript annotated with JSDoc, and
    // our tsconfig does not enable `allowJs` — without the `.d.ts` files, every message import
    // would be a "could not find a declaration file" error.
    //
    // The strategy is deliberately reduced to `globalVariable`: resolution lives in
    // `src/shell/locale.ts` (localStorage mirror → native shell → browser), and the server
    // remains the authority. Letting Paraglide read a cookie or the URL would introduce a
    // second source of truth, which would diverge from `app.language` without saying so.
    paraglideVitePlugin({
      project: './project.inlang',
      outdir: './src/paraglide',
      strategy: ['globalVariable', 'baseLocale'],
      emitTsDeclarations: true,
    }),
  ],
  build: {
    outDir: '../python/retina/resources/webui',
    emptyOutDir: true,
    target: 'es2022',
    sourcemap: true,
    // Monaco alone weighs ~3.1 MB (2.7 before the script editor added find, folding, hover and
    // signature help — cf. `console/monaco.ts`) and cannot be split up usefully. It is already
    // isolated in its own chunk, loaded when the console or a script is first opened — the
    // shell itself stays under 350 KB. The default warning would therefore flag nothing but it.
    chunkSizeWarningLimit: 3400,
  },
  // Two runners live side by side in this directory and would pick each other's files up:
  // vitest would try to execute `e2e/smoke.spec.ts` ("Playwright Test did not expect
  // test.beforeEach() to be called here"). Each therefore sees only its own directory —
  // Playwright through `testDir: './e2e'`, vitest through the explicit include below.
  test: {
    include: ['tests/**/*.test.ts'],
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: false },
      '/ws': { target: 'ws://127.0.0.1:8765', ws: true, changeOrigin: false },
    },
  },
});
