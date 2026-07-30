// Frontend bootstrap — the language first, the application second.
//
// Two lines, and they are not interchangeable. `resolveInitialLocale()` queries the
// `localStorage` mirror, then the native shell (`locale` IPC), then `navigator.language`; until
// it has answered, no module carrying labels must have been evaluated. Hence the **dynamic**
// import of `./app`: a static import would be hoisted above the `await` and the interface would
// render in the fallback language before switching under the user's eyes.
//
// Module-level `await` assumes an ES2022 target, which `vite.config.ts` and the `tsconfig`
// already set.

import { resolveInitialLocale } from './shell/locale';

await resolveInitialLocale();
await import('./app');
