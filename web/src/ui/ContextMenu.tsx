// Context menu — the right-click the whole shell was missing.
//
// # Why this is not a `MenuNode` of the command registry
//
// The title bar menus reference **global** commands by identifier
// (`shell/titlebar/menus.ts`), which guarantees them a single implementation and a displayable
// Python line. A contextual action, on the other hand, is a closure over **its target**:
// "delete *this* preview" makes no sense outside the click that designates it. Forcing it into
// the registry would create pseudo-commands there that the palette could not execute.
//
// Parity does not suffer: each action calls an echoed `app.*`, exactly like a menu entry. It is
// the *path* that is contextual, not the capability.

import { useEffect, useRef } from 'preact/hooks';
import { signal } from '@preact/signals';

export interface ContextMenuItem {
  label: string;
  /** Codicon name, without the prefix. */
  icon?: string;
  disabled?: boolean;
  /** Destructive action: rendered in red (deletion). */
  danger?: boolean;
  run: () => void;
}

export type ContextMenuNode = ContextMenuItem | 'separator';

interface ContextMenuRequest {
  x: number;
  y: number;
  items: readonly ContextMenuNode[];
}

const request = signal<ContextMenuRequest | null>(null);

/**
 * Opens the menu at the position of an event.
 *
 * To be called from an `onContextMenu`, after `preventDefault()` — otherwise the browser menu
 * would show on top (which is what happened everywhere until now).
 */
export function openContextMenu(event: MouseEvent, items: readonly ContextMenuNode[]): void {
  event.preventDefault();
  event.stopPropagation();
  if (items.length === 0) return;
  request.value = { x: event.clientX, y: event.clientY, items };
}

export function closeContextMenu(): void {
  request.value = null;
}

/** Mounted once by the workbench, like `PromptHost`. */
export function ContextMenuHost() {
  const current = request.value;
  const menuRef = useRef<HTMLDivElement>(null);

  // The keyboard and an outside click close it: a menu one can only leave by clicking an entry
  // is a trap, and Escape is the reflex.
  useEffect(() => {
    if (!current) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        closeContextMenu();
      }
    };
    const onDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) closeContextMenu();
    };
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('mousedown', onDown, true);
    // Scrolling or resizing would move the target out from under a menu that stayed in place.
    window.addEventListener('resize', closeContextMenu);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      window.removeEventListener('mousedown', onDown, true);
      window.removeEventListener('resize', closeContextMenu);
    };
  }, [current]);

  if (!current) return null;

  // Clamped inside the window: a right-click near the bottom edge would otherwise open a menu
  // off screen.
  const estimatedHeight = current.items.length * 24 + 8;
  const top = Math.min(current.y, Math.max(0, window.innerHeight - estimatedHeight));
  const left = Math.min(current.x, Math.max(0, window.innerWidth - 220));

  return (
    <div
      ref={menuRef}
      class="context-menu"
      role="menu"
      style={{ position: 'fixed', top: `${top}px`, left: `${left}px`, zIndex: 60 }}
    >
      {current.items.map((item, index) =>
        item === 'separator' ? (
          <div key={`sep${index}`} class="context-menu-separator" />
        ) : (
          <button
            key={item.label}
            class="context-menu-item"
            role="menuitem"
            disabled={item.disabled}
            data-danger={item.danger ? 'true' : undefined}
            onClick={() => {
              closeContextMenu();
              item.run();
            }}
          >
            <i
              class={`codicon codicon-${item.icon ?? 'blank'}`}
              aria-hidden="true"
              style={{ opacity: item.icon ? 1 : 0 }}
            />
            {item.label}
          </button>
        ),
      )}
    </div>
  );
}
