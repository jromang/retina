// Pure interface state — what has *no* Python mirror.
//
// The project's rule is that every capability goes through `app.*` and produces an echo. These two
// signals are the accepted exception: opening the palette or dropping a menu down changes nothing
// in the domain, they are navigation gestures within the interface. Echoing them would pollute the
// console with noise the user did not cause — the same reasoning as `layout.report`.
//
// They live here rather than in the components for a precise reason: `paletteOpen` has
// four callers (the Ctrl+Shift+P shortcut, the status bar, the command center, the Help menu).
// Putting it in `CommandPalette.tsx` would create an import cycle with `commands.ts`, which
// `menus.ts` already imports.

import { signal } from '@preact/signals';

/** Is the command palette open? */
export const paletteOpen = signal(false);

export function openPalette(): void {
  paletteOpen.value = true;
}

export function closePalette(): void {
  paletteOpen.value = false;
}

/** Is the shortcuts cheat sheet displayed? */
export const shortcutsOpen = signal(false);

/** Id of the drop-down menu open in the title bar (`null` = none). One at a time. */
export const openMenu = signal<string | null>(null);

export function closeMenus(): void {
  openMenu.value = null;
}
