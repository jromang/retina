// Keyboard navigation of the panel trees — the pure function behind the ARIA tree pattern.
//
// The arrows skip headers (`disabled`), Home/End jump to the focusable extremities, ←/→ follow
// the hierarchy through `level`. It is the same engine for all four panels.

import { describe, expect, it } from 'vitest';

import { nextIndex, type TreeItemSpec } from '../src/ui/treeNav';

const FLAT: TreeItemSpec[] = [
  { id: 'h1', disabled: true },
  { id: 'a' },
  { id: 'b' },
  { id: 'h2', disabled: true },
  { id: 'c' },
];

const NESTED: TreeItemSpec[] = [
  { id: 'w1', level: 1 },
  { id: 'p1', level: 2 },
  { id: 'p2', level: 2 },
  { id: 'w2', level: 1 },
];

describe('nextIndex', () => {
  it('moves down and up while skipping headers', () => {
    expect(nextIndex(FLAT, 1, 'ArrowDown')).toBe(2);
    expect(nextIndex(FLAT, 2, 'ArrowDown')).toBe(4); // skips h2
    expect(nextIndex(FLAT, 4, 'ArrowUp')).toBe(2);
    expect(nextIndex(FLAT, 1, 'ArrowUp')).toBe(1); // top stop (h1 not focusable)
    expect(nextIndex(FLAT, 4, 'ArrowDown')).toBe(4); // bottom stop
  });

  it('starts on the first focusable row from the neutral state', () => {
    expect(nextIndex(FLAT, -1, 'ArrowDown')).toBe(1);
  });

  it('Home and End aim at the focusable extremities', () => {
    expect(nextIndex(FLAT, 4, 'Home')).toBe(1);
    expect(nextIndex(FLAT, 1, 'End')).toBe(4);
  });

  it('← goes back up to the parent, → down to the first child', () => {
    expect(nextIndex(NESTED, 2, 'ArrowLeft')).toBe(0); // p2 → w1
    expect(nextIndex(NESTED, 0, 'ArrowRight')).toBe(1); // w1 → p1
    expect(nextIndex(NESTED, 3, 'ArrowRight')).toBe(3); // w2 has no child: stays put
    expect(nextIndex(NESTED, 0, 'ArrowLeft')).toBe(0); // root: stays put
  });

  it('ignores unknown keys', () => {
    expect(nextIndex(FLAT, 2, 'PageDown')).toBe(2);
  });
});
