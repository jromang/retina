// Resolving the language at startup, and reconciling it with the server.
//
// What can actually break here:
//
//   1. the **order of the sources** — a mirror ignored in favour of `navigator.language` would
//      bring the interface back to the system language on every launch, despite an explicit
//      choice;
//   2. the **reload loop** — if reconciliation reloaded without writing the mirror, the next
//      round would guess the same wrong language, reload, and so on. That is a failure that
//      makes the application unusable, not a cosmetic defect.

import { beforeEach, describe, expect, it, vi } from 'vitest';

/** Fake `localStorage`: Node provides none without `--localstorage-file`. */
function stubStorage(initial: Record<string, string> = {}) {
  const store = new Map(Object.entries(initial));
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
  });
  return store;
}

/** Fake `/api/ping`. `null` = silent server, which is what makes the fallbacks kick in. */
function stubServer(locale: string | null) {
  vi.stubGlobal('fetch', () =>
    locale === null
      ? Promise.reject(new Error('unreachable'))
      : Promise.resolve({ ok: true, json: () => Promise.resolve({ language: locale }) }),
  );
}

function stubShell(locale: string | null | undefined) {
  vi.stubGlobal('window', {
    __RETINA_SHELL__: locale !== undefined,
    retinaShell: locale === undefined ? undefined : { invoke: () => Promise.resolve(locale) },
  });
}

const documentElement = { lang: '' };
vi.stubGlobal('document', { documentElement });
vi.stubGlobal('navigator', { language: 'de-DE' });
stubStorage();
stubShell(undefined);
stubServer(null);

const { activeLocale, applyLocale, normalizeLocale, reconcileWithServer, resolveInitialLocale } =
  await import('../src/shell/locale');
// Namespace kept, not destructured: `overwriteGetLocale` **reassigns** the `getLocale` export,
// and destructuring would freeze the value as of the import — the test would then be
// interrogating a function nobody uses any more.
const runtime = await import('../src/paraglide/runtime');

beforeEach(() => {
  applyLocale('en');
  documentElement.lang = '';
});

describe('normalization', () => {
  it.each([
    ['fr', 'fr'],
    ['fr-FR', 'fr'],
    ['fr_FR', 'fr'],
    ['fr-FR.UTF-8', 'fr'],
    ['EN-us', 'en'],
    // A language we do not serve must not be retained: we fall through to the next source
    // rather than display a half-translated interface.
    ['de-DE', null],
    ['', null],
  ])('reduces %s to %s', (label, expected) => {
    expect(normalizeLocale(label)).toBe(expected);
  });

  it('rejects anything that is not a string', () => {
    expect(normalizeLocale(null)).toBeNull();
    expect(normalizeLocale(42)).toBeNull();
  });
});

describe('resolution at startup', () => {
  it('the server wins over every local guess', async () => {
    // This is *the* property that matters: the server translates parameter labels and the
    // documentation, and an interface speaking a different language than they do would be worse
    // than no i18n at all.
    stubServer('fr-FR');
    stubStorage({ 'retina.language': 'en' });
    stubShell('en-US');
    vi.stubGlobal('navigator', { language: 'en-US' });

    expect(await resolveInitialLocale()).toBe('fr');
  });

  it('the mirror takes over when the server does not answer', async () => {
    stubServer(null);
    stubStorage({ 'retina.language': 'fr' });
    stubShell('en-US');

    expect(await resolveInitialLocale()).toBe('fr');
  });

  it('failing a mirror, the native shell decides', async () => {
    stubServer(null);
    stubStorage();
    stubShell('fr-FR');

    expect(await resolveInitialLocale()).toBe('fr');
  });

  it('in browser mode, it is `navigator.language`', async () => {
    stubServer(null);
    stubStorage();
    stubShell(undefined); // no shell
    vi.stubGlobal('navigator', { language: 'fr-CA' });

    expect(await resolveInitialLocale()).toBe('fr');
  });

  it('falls back to English when no source says anything useful', async () => {
    stubServer(null);
    stubStorage();
    stubShell(null); // the shell is there but the OS does not answer
    vi.stubGlobal('navigator', { language: 'de-DE' });

    expect(await resolveInitialLocale()).toBe('en');
  });

  it("sets the document's `lang` attribute and Paraglide's `getLocale`", async () => {
    stubServer(null);
    stubStorage({ 'retina.language': 'fr' });

    await resolveInitialLocale();

    expect(documentElement.lang).toBe('fr');
    expect(runtime.getLocale()).toBe('fr');
    expect(activeLocale()).toBe('fr');
  });
});

describe('reconciliation with the server', () => {
  it('reloads when the server serves another language', () => {
    const store = stubStorage();
    applyLocale('en');
    const reload = vi.fn();

    expect(reconcileWithServer('fr', reload)).toBe(true);

    expect(reload).toHaveBeenCalledOnce();
    // The mirror is written **before** the reload: that is what prevents the loop.
    expect(store.get('retina.language')).toBe('fr');
  });

  it('does not reload when the guess was right', () => {
    stubStorage();
    applyLocale('fr');
    const reload = vi.fn();

    expect(reconcileWithServer('fr', reload)).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });

  it('ignores an unknown server language rather than reloading for nothing', () => {
    stubStorage();
    applyLocale('en');
    const reload = vi.fn();

    expect(reconcileWithServer('klingon', reload)).toBe(false);
    expect(reconcileWithServer(undefined, reload)).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });

  it('does not loop: after the reload, the guess is right', async () => {
    const store = stubStorage();
    stubServer(null);
    stubShell('en-US');
    applyLocale('en');
    const reload = vi.fn();

    reconcileWithServer('fr', reload);
    expect(reload).toHaveBeenCalledOnce();

    // What the next round would do: the mirror written above is read back at startup.
    expect(store.get('retina.language')).toBe('fr');
    expect(await resolveInitialLocale()).toBe('fr');
    expect(reconcileWithServer('fr', reload)).toBe(false);
    expect(reload).toHaveBeenCalledOnce();
  });
});
