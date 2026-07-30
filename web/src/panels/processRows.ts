// Row model of the process explorer — pure, hence testable without a DOM.
//
// The grouped list (category headers + items) is flattened into an array of rows of uniform
// height: that is what makes arithmetic windowing possible. 115 processes today, hundreds
// tomorrow (plugins) — without windowing, every keystroke in the search box re-renders that
// many DOM nodes.

import type { ProcessMeta } from '../api/types';
import { fold } from '../shell/commands';

export type ProcessRow =
  | { kind: 'header'; category: string; count: number }
  | { kind: 'item'; process: ProcessMeta };

export interface ProcessGroup {
  category: string;
  items: readonly ProcessMeta[];
}

/** Flatten the groups into rows, filtering included — an empty category disappears. */
export function processRows(groups: readonly ProcessGroup[], needle: string): ProcessRow[] {
  const folded = fold(needle);
  const rows: ProcessRow[] = [];
  for (const { category, items } of groups) {
    const visible =
      folded === '' ? items : items.filter((p) => fold(p.process_id).includes(folded));
    if (visible.length === 0) continue;
    rows.push({ kind: 'header', category, count: visible.length });
    for (const process of visible) rows.push({ kind: 'item', process });
  }
  return rows;
}

/** Window of rows to render for a given scroll position, with a smoothness margin. */
export function rowWindow(
  scrollTop: number,
  viewportHeight: number,
  total: number,
  rowHeight: number,
  overscan = 4,
): { start: number; end: number } {
  if (total === 0) return { start: 0, end: 0 };
  // bounded downwards too: a stale scrollTop (list refiltered) must not render empty
  const start = Math.min(
    Math.max(0, Math.floor(scrollTop / rowHeight) - overscan),
    total - 1,
  );
  const end = Math.min(total, Math.ceil((scrollTop + viewportHeight) / rowHeight) + overscan);
  return { start, end: Math.max(end, start + 1) };
}
