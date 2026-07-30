// Menu drop-down list, recursive (a submenu is one more MenuList).
//
// Behaviors taken from VS Code, in the order in which they matter:
//   ↑/↓ skip separators · → opens a submenu and enters it · ← leaves it · Esc closes
//   everything · hovering a submenu = opening after a short delay (otherwise it opens while
//   crossing the list on the way somewhere else).
//
// The items of a submenu are mounted **only while it is open**: the Process menu has
// 115 of them, keeping them in the DOM permanently would bring nothing.

import { formatShortcut } from '../keybindings';
import { useEffect, useRef, useState } from 'preact/hooks';

import { TablerIcon } from '../TablerIcon';
import type { Command } from '../commands';
import type { MenuNode } from './menus';

/** Delay before a hover opens a submenu — lets one cross without triggering. */
const SUBMENU_HOVER_MS = 200;

export interface MenuListProps {
  items: readonly MenuNode[];
  /** Resolves a `{kind:'command', id}` into a real action. */
  resolve: (id: string) => Command | undefined;
  /** Called after execution: closes the whole chain of menus. */
  onRun: () => void;
  /** ←/→ at the top level: move to the neighboring menu of the bar. */
  onSiblingMenu?: (delta: -1 | 1) => void;
  /** Absolute positioning of the top level (under the bar's button). */
  anchor?: { left: number; top: number };
  /** Depth: only level 0 is anchored to the window. */
  depth?: number;
}

interface Entry {
  node: MenuNode;
  label: string;
  shortcut?: string;
  /** Tabler icon, for process entries. */
  icon?: string;
  run?: () => void;
  submenu?: readonly MenuNode[];
}

/** Flattens the nodes into displayable entries, discarding the commands that cannot be found. */
function toEntries(items: readonly MenuNode[], resolve: (id: string) => Command | undefined): Entry[] {
  const out: Entry[] = [];
  for (const node of items) {
    if (node.kind === 'separator') {
      // No two separators in a row, and no leading separator: the lists are built
      // with optional sections, so gaps are normal.
      if (out.length && out[out.length - 1]?.node.kind !== 'separator') out.push({ node, label: '' });
      continue;
    }
    if (node.kind === 'submenu') {
      if (node.items.length) out.push({ node, label: node.label, submenu: node.items });
      continue;
    }
    if (node.kind === 'action') {
      const entry: Entry = { node, label: node.label, run: node.run };
      if (node.shortcut) entry.shortcut = node.shortcut;
      out.push(entry);
      continue;
    }
    const command = resolve(node.id);
    if (!command) continue; // an obsolete id disappears from the menu instead of staying inert
    const entry: Entry = { node, label: command.title, run: command.run };
    if (command.shortcut) entry.shortcut = command.shortcut;
    if (command.icon) entry.icon = command.icon;
    out.push(entry);
  }
  while (out.length && out[out.length - 1]?.node.kind === 'separator') out.pop();
  return out;
}

/** Position of a submenu: to the right of its item, folded left if it would overflow. */
function submenuAnchor(item: HTMLElement): { left: number; top: number } {
  const rect = item.getBoundingClientRect();
  const width = 220; // minimum width of a dropdown; enough to decide the side
  const left = rect.right + width > window.innerWidth ? rect.left - width : rect.right;
  return { left: Math.max(0, left), top: rect.top - 5 };
}

export function MenuList({
  items,
  resolve,
  onRun,
  onSiblingMenu,
  anchor,
  depth = 0,
}: MenuListProps) {
  const entries = toEntries(items, resolve);
  const [active, setActive] = useState(-1);
  const [openSub, setOpenSub] = useState<{ index: number; left: number; top: number } | null>(null);
  const rootRef = useRef<HTMLUListElement>(null);
  const hoverTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    rootRef.current?.focus();
    return () => window.clearTimeout(hoverTimer.current);
  }, []);

  const step = (from: number, delta: 1 | -1): number => {
    let index = from;
    for (let i = 0; i < entries.length; i += 1) {
      index = (index + delta + entries.length) % entries.length;
      if (entries[index]?.node.kind !== 'separator') return index;
    }
    return from;
  };

  /** Opens the submenu of `index`, measuring its `<li>` to anchor it. */
  const openSubmenuAt = (index: number) => {
    const li = rootRef.current?.querySelectorAll<HTMLElement>(':scope > li')[index];
    if (!li) return;
    setOpenSub({ index, ...submenuAnchor(li) });
  };

  const activate = (index: number) => {
    const entry = entries[index];
    if (!entry) return;
    if (entry.submenu) {
      openSubmenuAt(index);
      return;
    }
    entry.run?.();
    onRun();
  };

  const onKeyDown = (event: KeyboardEvent) => {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        setActive((i) => step(i, 1));
        break;
      case 'ArrowUp':
        event.preventDefault();
        setActive((i) => step(i < 0 ? 0 : i, -1));
        break;
      case 'ArrowRight':
        event.preventDefault();
        if (entries[active]?.submenu) openSubmenuAt(active);
        else if (depth === 0) onSiblingMenu?.(1);
        break;
      case 'ArrowLeft':
        event.preventDefault();
        if (openSub !== null) setOpenSub(null);
        else if (depth === 0) onSiblingMenu?.(-1);
        break;
      case 'Enter':
      case ' ':
        event.preventDefault();
        activate(active);
        break;
      case 'Escape':
        event.preventDefault();
        onRun();
        break;
      default:
        break;
    }
  };

  const style = anchor
    ? { position: 'fixed' as const, left: `${anchor.left}px`, top: `${anchor.top}px` }
    : undefined;

  return (
    <ul
      ref={rootRef}
      class="menu-dropdown"
      role="menu"
      tabIndex={-1}
      style={style}
      onKeyDown={onKeyDown}
    >
      {entries.map((entry, index) =>
        entry.node.kind === 'separator' ? (
          // Key by index: a separator has no identity of its own, and the list is never
          // reordered (it is rebuilt in full when the menu changes).
          <li key={`sep-${index}`} class="menu-separator" role="separator" />
        ) : (
          <li
            key={entry.label}
            class="menu-item"
            role="menuitem"
            aria-haspopup={entry.submenu ? 'menu' : undefined}
            aria-expanded={entry.submenu ? openSub?.index === index : undefined}
            data-active={active === index}
            onMouseEnter={() => {
              setActive(index);
              window.clearTimeout(hoverTimer.current);
              if (entry.submenu) {
                hoverTimer.current = window.setTimeout(() => openSubmenuAt(index), SUBMENU_HOVER_MS);
              } else {
                setOpenSub(null);
              }
            }}
            onMouseLeave={() => window.clearTimeout(hoverTimer.current)}
            onClick={(event) => {
              event.stopPropagation();
              activate(index);
            }}
          >
            {entry.icon ? <TablerIcon name={entry.icon} /> : null}
            <span class="menu-label">{entry.label}</span>
            {entry.shortcut && <span class="menu-shortcut">{formatShortcut(entry.shortcut)}</span>}
            {entry.submenu && <i class="codicon codicon-chevron-right menu-arrow" />}
            {entry.submenu && openSub?.index === index && (
              <MenuList
                items={entry.submenu}
                resolve={resolve}
                onRun={onRun}
                depth={depth + 1}
                anchor={{ left: openSub.left, top: openSub.top }}
              />
            )}
          </li>
        ),
      )}
    </ul>
  );
}
