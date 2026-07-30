// Keyboard navigation for panel trees and lists — the ARIA "tree" pattern.
//
// A single mechanism for all four panels (processes, windows, files, library): the container
// holds the focus and `aria-activedescendant` designates the active row. No *roving tabindex*:
// with a virtualized list, the focused row can be unmounted at any moment — the DOM focus would
// be lost, whereas an active index plus `scrollIntoView` survives recycling. The rows carry
// `tabIndex={-1}`: a single Tab stop per panel.

import { useMemo, useState } from 'preact/hooks';

export interface TreeItemSpec {
  /** Stable DOM id suffix (unique within the container). */
  id: string;
  /** ARIA depth (1 = root). Used by ←/→ (parent / first child). */
  level?: number;
  /** Non-activatable row — a group header. The arrow keys skip it. */
  disabled?: boolean;
}

/** Next active row for a given key — pure, tested without a DOM. */
export function nextIndex(items: readonly TreeItemSpec[], current: number, key: string): number {
  const enabled = (i: number) => items[i] !== undefined && !items[i]?.disabled;
  const step = (from: number, delta: number): number => {
    for (let i = from + delta; i >= 0 && i < items.length; i += delta) {
      if (enabled(i)) return i;
    }
    return from;
  };
  switch (key) {
    case 'ArrowDown':
      return step(current, 1);
    case 'ArrowUp':
      return step(current, -1);
    case 'Home':
      return step(-1, 1);
    case 'End':
      return step(items.length, -1);
    case 'ArrowLeft': {
      // go back up to the nearest ancestor (strictly lower level)
      const level = items[current]?.level ?? 1;
      for (let i = current - 1; i >= 0; i--) {
        if (enabled(i) && (items[i]?.level ?? 1) < level) return i;
      }
      return current;
    }
    case 'ArrowRight': {
      // descend to the first child, if it follows immediately
      const level = items[current]?.level ?? 1;
      const next = step(current, 1);
      return (items[next]?.level ?? 1) > level ? next : current;
    }
    default:
      return current;
  }
}

export interface TreeNavOptions {
  /** DOM id prefix — unique per panel instance. */
  idPrefix: string;
  items: readonly TreeItemSpec[];
  /** Enter/Space on the active row. */
  onActivate: (index: number) => void;
  /** Brings the row into the visible area (supplied by the virtualized lists). */
  scrollIntoView?: (index: number) => void;
  /** Container label for screen readers. */
  label: string;
}

export function useTreeNav({ idPrefix, items, onActivate, scrollIntoView, label }: TreeNavOptions) {
  const [activeIndex, setActiveIndex] = useState(-1);
  const domId = (index: number) => `${idPrefix}-${items[index]?.id ?? index}`;

  const reveal = useMemo(
    () =>
      scrollIntoView ??
      ((index: number) =>
        document.getElementById(domId(index))?.scrollIntoView({ block: 'nearest' })),
    [scrollIntoView, items],
  );

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      if (activeIndex >= 0 && !items[activeIndex]?.disabled) {
        event.preventDefault();
        onActivate(activeIndex);
      }
      return;
    }
    const next = nextIndex(items, activeIndex, event.key);
    if (next === activeIndex) return;
    event.preventDefault();
    setActiveIndex(next);
    reveal(next);
  };

  return {
    activeIndex,
    setActiveIndex,
    containerProps: {
      role: 'tree' as const,
      tabIndex: 0,
      'aria-label': label,
      'aria-activedescendant': activeIndex >= 0 ? domId(activeIndex) : undefined,
      onKeyDown,
    },
    itemProps: (index: number) => ({
      role: items[index]?.disabled ? undefined : ('treeitem' as const),
      id: domId(index),
      'aria-level': items[index]?.level ?? 1,
      'data-active': index === activeIndex || undefined,
      tabIndex: -1,
    }),
  };
}
