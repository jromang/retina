// `viewById` is the client-side global addressing of views: the real-time preview uses it to
// find the view it represents, which is not necessarily the active one. The case that matters
// is the **preview** — it lives in `win.views` just like a main view does, and a sweep that
// only looked at main views would miss it silently.

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });
vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => undefined });

const { snapshot, viewById } = await import('../src/state/store');

type Snapshot = typeof snapshot.value;

function view(id: string, isPreview = false) {
  return {
    id,
    is_preview: isPreview,
    width: 100,
    height: 80,
    channels: 3,
    pixel_gen: 1,
    history: { index: 0, labels: ['initial'] },
    stf: { enabled: false, channels: [] },
  };
}

function win(id: string, views: ReturnType<typeof view>[]) {
  return { id, views };
}

beforeEach(() => {
  snapshot.value = {
    windows: [
      win('Test01', [view('Test01'), view('Test01_Preview01', true)]),
      win('Test02', [view('Test02')]),
    ],
  } as unknown as Snapshot;
});

describe('viewById', () => {
  it('finds a main view along with its window', () => {
    const found = viewById('Test02');
    expect(found?.view.id).toBe('Test02');
    expect(found?.win.id).toBe('Test02');
  });

  it('finds a preview — it is a view like any other', () => {
    const found = viewById('Test01_Preview01');
    expect(found?.view.is_preview).toBe(true);
    expect(found?.win.id).toBe('Test01');
  });

  it('returns null for a closed view — the panel has to be able to say so', () => {
    expect(viewById('Vanished')).toBeNull();
  });

  it('returns null without a snapshot', () => {
    snapshot.value = null;
    expect(viewById('Test01')).toBeNull();
  });
});
