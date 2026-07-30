// Menu bar embedded in the title bar (VS Code style).
//
// The signature behavior, the one you notice when it is missing: once **one** menu is open,
// hovering another title switches to it without a click. That is what makes the bar
// browsable with the mouse.
//
// Closing on an outside click goes through a full-screen scrim rather than a listener on
// `document`: the same mechanism as the palette (`.palette-scrim`), and above all no race between
// the item's `click` and the one that closes.

import { useMemo, useRef } from 'preact/hooks';

import { processesByCategory } from '../../state/store';
import { commandIndex } from '../commands';
import { recentFiles, recentProjects } from '../../project/project';
import { closeMenus, openMenu } from '../uiState';
import { MenuList } from './Menu';
import { buildMenus } from './menus';

interface Props {
  perspectives: readonly string[];
}

export function MenuBar({ perspectives }: Props) {
  const categories = processesByCategory.value;
  // The recents feed the **same** call on both sides: the menu references them by id,
  // the registry provides the commands. Desynchronizing them would give inert entries —
  // which `web/tests/menus.test.ts` refuses.
  const recent = { files: recentFiles.value, projects: recentProjects.value };
  const menus = useMemo(
    () => buildMenus({ perspectives, processesByCategory: categories, recent }),
    [perspectives, categories, recent.files, recent.projects],
  );
  const index = useMemo(
    () => commandIndex(perspectives, categories.flatMap((group) => [...group.items]), recent),
    [perspectives, categories, recent.files, recent.projects],
  );

  const barRef = useRef<HTMLDivElement>(null);
  const current = openMenu.value;
  const currentIndex = menus.findIndex((menu) => menu.id === current);
  const active = currentIndex >= 0 ? menus[currentIndex] : undefined;

  const anchorFor = (id: string) => {
    const button = barRef.current?.querySelector<HTMLElement>(`[data-menu="${id}"]`);
    if (!button) return undefined;
    const rect = button.getBoundingClientRect();
    return { left: rect.left, top: rect.bottom };
  };

  const sibling = (delta: -1 | 1) => {
    if (currentIndex < 0) return;
    const next = menus[(currentIndex + delta + menus.length) % menus.length];
    if (next) openMenu.value = next.id;
  };

  return (
    <>
      <div class="menubar" ref={barRef} role="menubar">
        {menus.map((menu) => (
          <button
            key={menu.id}
            type="button"
            class="menubar-item"
            data-menu={menu.id}
            data-open={current === menu.id}
            aria-haspopup="menu"
            aria-expanded={current === menu.id}
            onClick={() => {
              openMenu.value = current === menu.id ? null : menu.id;
            }}
            // The VS Code gesture: we only "steal" the hover if a menu is already dropped down.
            onMouseEnter={() => {
              if (current !== null) openMenu.value = menu.id;
            }}
          >
            {menu.label}
          </button>
        ))}
      </div>
      {active && (
        <>
          <div class="menu-scrim" onPointerDown={closeMenus} />
          <MenuList
            items={active.items}
            resolve={(id) => index.get(id)}
            onRun={closeMenus}
            onSiblingMenu={sibling}
            {...(anchorFor(active.id) ? { anchor: anchorFor(active.id)! } : {})}
          />
        </>
      )}
    </>
  );
}
