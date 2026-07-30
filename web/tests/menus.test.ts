// The menu model, put under test where it can actually break.
//
// Two checks carry the whole file:
//
//   1. **every referenced id resolves** — the likeliest failure mode of a model that points at
//      the registry by string is a mistyped id, and it only shows up on click, on a menu that
//      does nothing;
//   2. **every command reachable from a menu carries its Python line** — the console-completeness
//      pillar of ARCHITECTURE.md put under automatic test, rather than left to code review.

import { describe, expect, it, vi } from 'vitest';

import type { ProcessMeta } from '../src/api/types';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const { buildMenus, referencedCommandIds } = await import('../src/shell/titlebar/menus');
const { commandIndex } = await import('../src/shell/commands');
// Labels come from the catalogue, never copied over: the test checks the *structure* of the
// menu, not the translation. Copying them would make the structure fail at the first reworded
// phrase.
const { m } = await import('../src/paraglide/messages');

function process(id: string, category: string): ProcessMeta {
  return {
    process_id: id,
    category,
    is_global: false,
    is_maskable: true,
    creates_window: false,
    supports_realtime: false,
    has_doc: true,
    icon: 'wand',
    parameters: [],
  };
}

const CATALOG = [
  { category: 'Convolution', items: [process('GaussianConvolution', 'Convolution')] },
  { category: 'Geometry', items: [process('Invert', 'Geometry'), process('Rescale', 'Geometry')] },
];
const PERSPECTIVES = ['Processing', 'Inspection', 'Script', 'My layout'];

const RECENT = {
  files: ['/data/m31.fits', '/data/m42.fits'],
  projects: ['/data/m31.retina'],
};

const menus = buildMenus({
  perspectives: PERSPECTIVES,
  processesByCategory: CATALOG,
  recent: RECENT,
});
const index = commandIndex(PERSPECTIVES, CATALOG.flatMap((group) => group.items), RECENT);

describe('menu structure', () => {
  it('exposes the seven menus, in order', () => {
    expect(menus.map((menu) => menu.label)).toEqual([
      m.menu_file(),
      m.menu_edit(),
      m.menu_view(),
      m.menu_process(),
      m.menu_layout(),
      m.menu_panels(),
      m.menu_help(),
    ]);
  });

  it('groups the processes into one submenu per category', () => {
    const processMenu = menus.find((menu) => menu.id === 'process');
    expect(processMenu?.items.map((item) => item.kind)).toEqual(['submenu', 'submenu']);

    const labels = processMenu?.items.map((item) =>
      item.kind === 'submenu' ? item.label : null,
    );
    expect(labels).toEqual(['Convolution', 'Geometry']);
  });

  it('covers exactly the injected catalogue', () => {
    const ids = referencedCommandIds(menus).filter((id) => id.startsWith('process.'));
    expect(ids.sort()).toEqual(
      ['process.GaussianConvolution', 'process.Invert', 'process.Rescale'].sort(),
    );
  });

  it('only exposes user perspectives when there are some', () => {
    const ids = referencedCommandIds(menus);
    expect(ids).toContain('layout.perspective.My layout');

    const withoutCustom = buildMenus({
      perspectives: ['Processing', 'Inspection', 'Script'],
      processesByCategory: CATALOG,
    });
    expect(
      referencedCommandIds(withoutCustom).some((id) => id.startsWith('layout.perspective.')),
    ).toBe(false);
  });
});

describe('consistency with the command registry', () => {
  it('resolves every referenced id', () => {
    const missing = referencedCommandIds(menus).filter((id) => !index.has(id));
    expect(missing, `ids not found in the registry: ${missing.join(', ')}`).toEqual([]);
  });

  it('gives every menu command its equivalent Python line', () => {
    // Console-completeness: a menu entry with no `python` is a capability reserved to the
    // interface — the architectural bug that ARCHITECTURE.md forbids.
    const silent = referencedCommandIds(menus)
      .map((id) => index.get(id))
      .filter((command) => command && !command.python)
      .map((command) => command!.id);
    expect(silent, `commands with no Python echo: ${silent.join(', ')}`).toEqual([]);
  });
});

describe('recent paths', () => {
  it('groups the recents into submenus whose every entry resolves', () => {
    const fileMenu = menus.find((menu) => menu.id === 'file');
    const labels = fileMenu?.items
      .filter((item) => item.kind === 'submenu')
      .map((item) => (item.kind === 'submenu' ? item.label : ''));
    expect(labels).toEqual([m.menu_recent_files(), m.menu_recent_projects()]);

    const ids = referencedCommandIds(menus).filter((id) => id.startsWith('recent.'));
    expect(ids.sort()).toEqual(
      [
        'recent.file./data/m31.fits',
        'recent.file./data/m42.fits',
        'recent.project./data/m31.retina',
      ].sort(),
    );
    expect(ids.every((id) => index.has(id))).toBe(true);
  });

  it('replaces an empty submenu with an inert entry, not with a trap', () => {
    // An empty submenu: you click, nothing opens, and you cannot tell whether the application
    // failed to respond or there is simply nothing to show.
    const withoutRecents = buildMenus({
      perspectives: PERSPECTIVES,
      processesByCategory: CATALOG,
    });
    const fileMenu = withoutRecents.find((menu) => menu.id === 'file');
    const inert = fileMenu?.items.filter((item) => item.kind === 'action');

    expect(inert?.map((item) => (item.kind === 'action' ? item.label : ''))).toEqual([
      m.menu_empty({ label: m.menu_recent_files() }),
      m.menu_empty({ label: m.menu_recent_projects() }),
    ]);
    expect(referencedCommandIds(withoutRecents).some((id) => id.startsWith('recent.'))).toBe(false);
  });

  it('gives every recent its Python line — a click must be a typable line', () => {
    expect(index.get('recent.file./data/m31.fits')?.python).toBe('app.open("/data/m31.fits")');
    expect(index.get('recent.project./data/m31.retina')?.python).toBe(
      'app.open_project("/data/m31.retina")',
    );
  });

  it('exposes the project commands in the File menu', () => {
    const ids = referencedCommandIds(menus);
    for (const id of ['project.open', 'project.save', 'project.save_as', 'project.close']) {
      expect(ids, `${id} missing from the menu`).toContain(id);
      expect(index.get(id)?.python, `${id} has no Python line`).toBeTruthy();
    }
  });
});
