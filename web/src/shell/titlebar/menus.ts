// Model of the title bar menus — **data**, not components.
//
// # Why a model separate from the command registry
//
// `commands.ts` is a flat list: an id, a title, a category, a Python line. A menu
// is a tree, with separators and submenus, and its order is an ergonomics
// decision — not the registry's declaration order. Filtering `baseCommands()` by category
// would give an order we merely endure, could not express a separator, and would merge "View" and
// "Edit", which live in the same array on the registry side.
//
// Hence the separation: the registry stays the single source of the **actions** (one
// implementation, one Python echo) and the model below only **references them by id**. A mistyped
// id is then wrong data, which `web/tests/menus.test.ts` catches — instead of a menu that does
// nothing on click.
//
// # What is deliberately not here
//
// No "Quit" entry: `app.quit()` does not exist, and the ✕ button of the title bar
// plays that role. More generally, the window chrome (minimize/maximize/close) has **no**
// `app.*` equivalent and is not meant to have one: the console-completeness pillar covers *domain*
// actions, not the management of the OS window. Do not "fix" this point.

import { m } from '../../paraglide/messages';
import type { ProcessMeta } from '../../api/types';
import { EMPTY_RECENT, MASK_DISPLAY_MODES, TRANSPARENCY_MODES, type RecentPaths } from '../commands';
import { BUILTIN_PERSPECTIVES, PANELS, ZONES } from '../panels';
import { openPalette, shortcutsOpen } from '../uiState';

const openShortcuts = () => {
  shortcutsOpen.value = true;
};

export type MenuNode =
  /** References a command from the registry, resolved at display time. */
  | { kind: 'command'; id: string }
  | { kind: 'separator' }
  | { kind: 'submenu'; label: string; items: MenuNode[] }
  /** Pure interface action, without a Python echo (see header). Reserved for the chrome. */
  | { kind: 'action'; label: string; shortcut?: string; run: () => void };

export interface MenuDef {
  id: string;
  label: string;
  items: MenuNode[];
}

const cmd = (id: string): MenuNode => ({ kind: 'command', id });
const sep: MenuNode = { kind: 'separator' };

export interface MenuInputs {
  perspectives: readonly string[];
  /** Processes grouped by category — the shape `store.processesByCategory` already produces. */
  processesByCategory: readonly { category: string; items: readonly ProcessMeta[] }[];
  /** Recent paths. The matching ids come from `recentCommands`, in the registry:
   *  not injecting them here **and** in `commandIndex` would make a menu pointing into the void. */
  recent?: RecentPaths;
}

/**
 * Submenu of recent paths, or an inert entry when there are none.
 *
 * An empty submenu would be a trap: one clicks, nothing opens, and one cannot tell whether
 * the application failed to answer or whether there is nothing to show.
 */
function recentSubmenu(label: string, prefix: string, paths: readonly string[]): MenuNode {
  if (paths.length === 0) {
    return { kind: 'action', label: m.menu_empty({ label }), run: () => undefined };
  }
  return { kind: 'submenu', label, items: paths.map((path) => cmd(`${prefix}${path}`)) };
}

export function buildMenus({
  perspectives,
  processesByCategory,
  recent = EMPTY_RECENT,
}: MenuInputs): MenuDef[] {
  const custom = perspectives.filter(
    (name) => !(BUILTIN_PERSPECTIVES as readonly string[]).includes(name),
  );

  return [
    {
      id: 'file',
      label: m.menu_file(),
      items: [
        cmd('file.open'),
        recentSubmenu(m.menu_recent_files(), 'recent.file.', recent.files),
        cmd('file.save_as'),
        sep,
        // The project — the whole session — is what one opens and saves most often
        // once the work has started: right under the image, not in some corner.
        cmd('project.open'),
        recentSubmenu(m.menu_recent_projects(), 'recent.project.', recent.projects),
        cmd('project.save'),
        cmd('project.save_as'),
        cmd('project.close'),
        sep,
        // Script mode is the first pillar: it belongs in the menu one opens
        // and saves from, not in some corner.
        cmd('script.new'),
        cmd('script.open'),
        cmd('script.save'),
        cmd('script.save_as'),
        cmd('script.run'),
        cmd('script.run_file'),
        cmd('container.new'),
        cmd('console.to_script'),
        sep,
        // Preprocessing is looked for here, not in "Panels": it is what a
        // session starts with, before even having an image open.
        cmd('pipeline.show'),
        // Sorting one's frames immediately follows preprocessing: same place, not drowned
        // in "Panels" among thirteen entries.
        cmd('selector.show'),
        cmd('blink.show'),
        sep,
        cmd('file.close_window'),
      ],
    },
    {
      id: 'edit',
      label: m.menu_edit(),
      items: [cmd('edit.undo'), cmd('edit.redo')],
    },
    {
      id: 'view',
      label: m.menu_view(),
      items: [
        cmd('view.autostretch'),
        sep,
        cmd('view.zoom_in'),
        cmd('view.zoom_out'),
        cmd('view.zoom_11'),
        cmd('view.zoom_fit'),
        sep,
        // Comparing: until now the two gestures existed only in the code — a key
        // nothing advertised and an icon without a label.
        cmd('view.compare_ab'),
        cmd('view.link'),
        cmd('view.unlink'),
        sep,
        // Masks get a top-level menu of their own elsewhere; here a submenu of "View"
        // is enough, and keeps them next to the other display settings. The mask rendering
        // is itself a sub-submenu: ten flat modes would drown the five actions.
        {
          kind: 'submenu' as const,
          label: m.menu_mask(),
          items: [
            cmd('mask.pick'),
            cmd('mask.remove'),
            sep,
            cmd('mask.toggle_visible'),
            cmd('mask.toggle_enabled'),
            cmd('mask.toggle_inverted'),
            sep,
            {
              kind: 'submenu' as const,
              label: m.menu_mask_render(),
              items: MASK_DISPLAY_MODES.map(([mode]) => cmd(`mask.display.${mode}`)),
            },
          ],
        },
        {
          kind: 'submenu' as const,
          label: m.menu_transparency(),
          items: TRANSPARENCY_MODES.map(([mode]) => cmd(`view.transparency.${mode}`)),
        },
      ],
    },
    {
      id: 'process',
      label: m.menu_process(),
      // One submenu per category: 115 flat entries would be unreadable, and this is the
      // hierarchy the process explorer already uses.
      items: processesByCategory.map(({ category, items }) => ({
        kind: 'submenu' as const,
        label: category,
        items: items.map((process) => cmd(`process.${process.process_id}`)),
      })),
    },
    {
      id: 'layout',
      label: m.menu_layout(),
      items: [
        cmd('layout.perspective_1'),
        cmd('layout.perspective_2'),
        cmd('layout.perspective_3'),
        ...(custom.length ? [sep, ...custom.map((name) => cmd(`layout.perspective.${name}`))] : []),
        sep,
        cmd('layout.save'),
        cmd('layout.delete'),
        sep,
        cmd('layout.reset'),
        cmd('layout.toggle_lock'),
      ],
    },
    {
      id: 'panels',
      label: m.menu_panels(),
      items: [
        ...ZONES.map((zone) => cmd(`zone.${zone}`)),
        sep,
        ...PANELS.map((panel) => cmd(`panel.${panel}`)),
      ],
    },
    {
      id: 'help',
      label: m.menu_help(),
      // Two deliberate `kind: 'action'`s: opening the palette or the shortcuts cheat sheet
      // changes nothing in the domain, so there is no Python line to display. This is
      // exactly the case that node exists to cover (see the file header).
      items: [
        cmd('panel.doc'),
        sep,
        {
          kind: 'action',
          label: m.cmd_palette_open(),
          shortcut: 'Ctrl+Shift+P',
          run: openPalette,
        },
        { kind: 'action', label: m.menu_shortcuts(), run: openShortcuts },
        sep,
        // The language lives in "Help" because that is where one looks for what concerns
        // the application itself, and not a process. Three entries, one of them "system".
        {
          kind: 'submenu' as const,
          label: m.menu_language(),
          items: [cmd('language.auto'), cmd('language.en'), cmd('language.fr')],
        },
        sep,
        // What Retina bundles and under which license. Its place is here: it is the
        // application that is at stake, not a process.
        cmd('panel.credits'),
      ],
    },
  ];
}

/** Every command id referenced, submenus included — used by the tests. */
export function referencedCommandIds(menus: readonly MenuDef[]): string[] {
  const out: string[] = [];
  const walk = (items: readonly MenuNode[]) => {
    for (const item of items) {
      if (item.kind === 'command') out.push(item.id);
      else if (item.kind === 'submenu') walk(item.items);
    }
  };
  walk(menus.flatMap((menu) => menu.items));
  return out;
}
