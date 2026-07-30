// `applyCommand` — the entry point for everything the server pushes to the layout.
//
// The case that matters is `set_zone_visible`: the server sends the panel list **already
// resolved** (it is the one that remembers the last active panel). If the client started
// replaying that logic, there would be two memories to keep in agreement — and collapsing then
// expanding would reopen the wrong panel as soon as they diverged.

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_VISIBLE } from '../src/shell/panels';

// vitest runs in a Node environment, with no DOM (a deliberate choice: these tests are about pure
// transformations, not rendering). But `layoutClient` imports the RPC client, which reads the
// token from the URL **when the module loads**. So we set up the bare minimum before the dynamic
// import — rather than pulling in jsdom for three properties.
vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const { applyCommand, panelVisible, zoneVisible } = await import('../src/shell/layoutClient');

beforeEach(() => {
  panelVisible.value = { ...DEFAULT_VISIBLE };
});

describe('applyCommand — set_zone_visible', () => {
  it('collapses a zone by closing all of its panels', () => {
    applyCommand({ op: 'set_zone_visible', zone: 'bottom', visible: false, panels: [] });

    expect(panelVisible.value.console).toBe(false);
    expect(panelVisible.value.rtp).toBe(false);
    expect(zoneVisible.value.bottom).toBe(false);
  });

  it('expands by opening only the panels the server dictates', () => {
    applyCommand({ op: 'set_zone_visible', zone: 'sidebar', visible: false, panels: [] });
    applyCommand({ op: 'set_zone_visible', zone: 'sidebar', visible: true, panels: ['history'] });

    expect(panelVisible.value.history).toBe(true);
    expect(panelVisible.value.explorer).toBe(false); // and above all NOT the default
    expect(zoneVisible.value.sidebar).toBe(true);
  });

  it('does not touch panels in other zones', () => {
    applyCommand({ op: 'set_zone_visible', zone: 'sidebar', visible: false, panels: [] });

    expect(panelVisible.value.console).toBe(true);
    expect(panelVisible.value.stf).toBe(true);
  });

  it('ignores a command with no zone rather than closing everything', () => {
    const before = { ...panelVisible.value };
    applyCommand({ op: 'set_zone_visible', panels: [] });
    expect(panelVisible.value).toEqual(before);
  });
});

describe('zoneVisible — derived, never stored', () => {
  it('follows a plain set_visible', () => {
    applyCommand({ op: 'set_zone_visible', zone: 'bottom', visible: false, panels: [] });
    expect(zoneVisible.value.bottom).toBe(false);

    // A panel reopened on its own makes its zone visible, with no zone command involved.
    applyCommand({ op: 'set_visible', panel: 'rtp', visible: true });
    expect(zoneVisible.value.bottom).toBe(true);
  });

  it('follows the sidebar’s exclusivity', () => {
    applyCommand({ op: 'activate', panel: 'library' });
    expect(zoneVisible.value.sidebar).toBe(true);
    expect(panelVisible.value.explorer).toBe(false);
  });
});

describe('layout serialization', () => {
  it('carries the zone sizes, not just visibility', async () => {
    // They used to live in a `useState` inside Workbench: a saved perspective restored only panel
    // visibility, never their width.
    const { serializeLayout } = await import('../src/shell/layoutClient');
    const { setZoneSize, zoneSizes, DEFAULT_ZONE_SIZES } = await import('../src/shell/zoneSizes');

    setZoneSize('sidebar', 420);
    const blob = serializeLayout();

    expect(blob.sizes?.sidebar).toBe(420);
    zoneSizes.value = { ...DEFAULT_ZONE_SIZES };
    applyCommand({ op: 'load_perspective', layout: blob });
    expect(zoneSizes.value.sidebar).toBe(420);
  });

  it('reloads a perspective saved before that field existed', async () => {
    const { zoneSizes, DEFAULT_ZONE_SIZES } = await import('../src/shell/zoneSizes');
    zoneSizes.value = { ...DEFAULT_ZONE_SIZES };

    applyCommand({ op: 'load_perspective', layout: { visible: { console: false } } });

    expect(panelVisible.value.console).toBe(false);
    expect(zoneSizes.value).toEqual(DEFAULT_ZONE_SIZES);
  });

  it('drops the id of a panel that has since been removed', () => {
    // A perspective saved by an older version still carries `journal`, deleted in July 2026. Its
    // key must not enter the mirror: the server already filters it out, and the client would
    // otherwise end up holding state that nothing renders.
    applyCommand({
      op: 'load_perspective',
      layout: { visible: { console: false, journal: true } },
    });

    expect(panelVisible.value.console).toBe(false);
    expect('journal' in panelVisible.value).toBe(false);
  });

  it('ignores an absurd size rather than breaking the grid', async () => {
    const { zoneSizes, applyZoneSizes, DEFAULT_ZONE_SIZES } = await import(
      '../src/shell/zoneSizes'
    );
    zoneSizes.value = { ...DEFAULT_ZONE_SIZES };

    applyZoneSizes({ sidebar: 'large', right: -10, bottom: 220 });

    expect(zoneSizes.value.sidebar).toBe(DEFAULT_ZONE_SIZES.sidebar);
    expect(zoneSizes.value.right).toBe(DEFAULT_ZONE_SIZES.right);
    expect(zoneSizes.value.bottom).toBe(220);
  });
});
