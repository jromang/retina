// Resolution of the interface language.
//
// # Who decides
//
// The **server** decides (`app.language`, see `python/retina/i18n.py`): it is the server that
// translates parameter labels, preprocessing notes and documentation, and an
// interface speaking a different language than its own forms would be worse than no
// i18n at all.
//
// So we **ask it before the first render**, through a `GET /api/ping` — the only route
// that answers without a token, and which already serves to tell whether the server is up. A
// round trip on the loopback costs less than a millisecond; it is done while the browser is
// still loading the rest of the bundle.
//
// *That was not the first version.* It guessed the language locally then corrected itself
// at the `hello` by **reloading** the page. It works, but the "wrong guess" case is not
// the exception: a browser configured in English on a French machine triggers it on every
// first load. The Playwright scenarios showed it unambiguously — the page
// reloaded from under the tests' feet, between the render and the first click. A correction that
// always happens is not a correction, it is the normal path.
//
// What remains, then, as fallbacks and in this order: the `localStorage` mirror (last known
// language), the system locale through the native shell, `navigator.language`, English. They only
// serve if the server does not answer — which, since the page comes from it, is mostly theoretical.
//
// # The reload does remain — but for the one case where it makes sense
//
// Changing language during a session reloads the page. Paraglide's message functions
// are dynamic, but our **tables** are not: `commands.ts`, `panels.ts` and `menus.ts`
// build their labels when their module is evaluated. Making them reactive would require
// turning fifty constants into signals for a gesture one performs once per installation.
// VS Code reloads too. And the reload solves a second problem for free: the process
// catalog (`process.list`) is only requested once per session, yet its labels are
// translated by the server.
//
// This is why Paraglide's `setLocale()` is **never** called: the language is changed through
// `app.set_language` (RPC `project.set_language`), which is the console-parity route.

import { baseLocale, isLocale, overwriteGetLocale, type Locale } from '../paraglide/runtime';

/** Key of the mirror. Distinct from Paraglide's: it is *our* resolution that gets remembered. */
const MIRROR_KEY = 'retina.language';

let current: Locale = baseLocale;

/** Reduces a BCP-47 tag (`fr-FR`) to a served locale, or `null`. */
export function normalizeLocale(tag: unknown): Locale | null {
  if (typeof tag !== 'string' || !tag) return null;
  const base = tag.trim().replace('_', '-').split('.')[0]!.split('-')[0]!.toLowerCase();
  return isLocale(base) ? base : null;
}

function readMirror(): Locale | null {
  try {
    return normalizeLocale(localStorage.getItem(MIRROR_KEY));
  } catch {
    // `localStorage` throws when third-party cookies are blocked, or in old private
    // browsing. Losing the mirror costs one reload at startup, not the session.
    return null;
  }
}

function writeMirror(locale: Locale): void {
  try {
    localStorage.setItem(MIRROR_KEY, locale);
  } catch {
    /* see readMirror */
  }
}

/** System locale, asked of the native shell. `null` in browser mode. */
async function shellLocale(): Promise<Locale | null> {
  const shell = window.retinaShell;
  if (window.__RETINA_SHELL__ !== true || typeof shell?.invoke !== 'function') return null;
  try {
    return normalizeLocale(await shell.invoke('locale', {}));
  } catch {
    return null;
  }
}

/**
 * Effective language of the server, asked of `/api/ping`.
 *
 * Without a token: this is the public route, and it says nothing more than "I am up".
 * A failure (server not ready yet, page served from a cache) returns `null` and hands
 * over to the fallbacks.
 */
async function serverLocale(): Promise<Locale | null> {
  try {
    const response = await fetch('/api/ping', { cache: 'no-store' });
    if (!response.ok) return null;
    return normalizeLocale(((await response.json()) as { language?: unknown }).language);
  } catch {
    return null;
  }
}

/**
 * Resolves the language of the first render, and installs it.
 *
 * To be called **before** importing anything that builds labels — that is the whole
 * point of the two-file bootstrap (`main.tsx` then `app.tsx`).
 */
export async function resolveInitialLocale(): Promise<Locale> {
  const locale =
    (await serverLocale()) ??
    readMirror() ??
    (await shellLocale()) ??
    normalizeLocale(navigator.language) ??
    baseLocale;
  applyLocale(locale);
  writeMirror(locale);
  return locale;
}

/** Installs *locale*: Paraglide's `getLocale()`, and the document's `lang` attribute. */
export function applyLocale(locale: Locale): void {
  current = locale;
  overwriteGetLocale(() => current);
  document.documentElement.lang = locale;
}

/** Language the interface currently serves. */
export function activeLocale(): Locale {
  return current;
}

/**
 * Confronts the startup guess with what the server really serves.
 *
 * Returns `true` if a reload was requested. The mirror is written **before** the reload:
 * that is what prevents the loop — on the next round, the guess is right and nothing
 * diverges any more.
 */
export function reconcileWithServer(
  effective: unknown,
  reload: () => void = () => location.reload(),
): boolean {
  const server = normalizeLocale(effective);
  if (server === null || server === current) return false;
  writeMirror(server);
  reload();
  return true;
}
