// Tree model of the file explorer.
//
// What this file really watches for are the three ways a lazily expanding tree lies: showing the
// children of a folder we have not read yet, asking the server again for what we already have
// (or for what nobody is looking at), and losing a branch's state because we collapsed its
// parent.

import { describe, expect, it } from 'vitest';

import {
  EMPTY_TREE,
  type FileEntry,
  type FileTree,
  flattenTree,
  invalidate,
  joinPath,
  pendingPaths,
  toggleExpanded,
  withEntries,
  withFailure,
  withLoading,
  withRoot,
} from '../src/panels/fileTree';

const dir = (name: string): FileEntry => ({ name, is_dir: true, size: 0, mtime: 0 });
const file = (name: string, size = 42): FileEntry => ({ name, is_dir: false, size, mtime: 1 });

/** `/data` → `lights/` (→ `L/`, `sub.fits`), `darks/`, `notes.txt`. */
function sample(): FileTree {
  let tree = withRoot(EMPTY_TREE, '/data');
  tree = withEntries(tree, '/data', [dir('lights'), dir('darks'), file('notes.txt')]);
  tree = withEntries(tree, '/data/lights', [dir('L'), file('sub.fits')]);
  tree = withEntries(tree, '/data/lights/L', [file('L_001.fits')]);
  return tree;
}

const names = (tree: FileTree) => flattenTree(tree).map((row) => row.entry.name);

describe('joinPath', () => {
  it("infers the separator from the path, not from the browser — the disk is the server's", () => {
    expect(joinPath('/data', 'x.fits')).toBe('/data/x.fits');
    expect(joinPath('/data/', 'x.fits')).toBe('/data/x.fits');
    expect(joinPath('C:\\data', 'x.fits')).toBe('C:\\data\\x.fits');
    expect(joinPath('C:\\', 'x.fits')).toBe('C:\\x.fits');
  });
});

describe('flattenTree', () => {
  it('no root, nothing — only the server knows its own home folder', () => {
    expect(flattenTree(EMPTY_TREE)).toEqual([]);
  });

  it('fully collapsed, the tree is exactly the old flat list', () => {
    const rows = flattenTree(sample());
    expect(rows.map((row) => row.entry.name)).toEqual(['lights', 'darks', 'notes.txt']);
    expect(rows.every((row) => row.depth === 0)).toBe(true);
    expect(rows.map((row) => row.path)).toEqual([
      '/data/lights',
      '/data/darks',
      '/data/notes.txt',
    ]);
  });

  it('expands in place, at the parent depth, without touching the server order', () => {
    let tree = toggleExpanded(sample(), '/data/lights');
    expect(flattenTree(tree).map((row) => [row.entry.name, row.depth])).toEqual([
      ['lights', 0],
      ['L', 1],
      ['sub.fits', 1],
      ['darks', 0],
      ['notes.txt', 0],
    ]);
    tree = toggleExpanded(tree, '/data/lights/L');
    expect(names(tree)).toEqual(['lights', 'L', 'L_001.fits', 'sub.fits', 'darks', 'notes.txt']);
    expect(flattenTree(tree)[2]?.depth).toBe(2);
  });

  it('a folder expanded but not yet loaded yields its own row and nothing more', () => {
    let tree = withRoot(EMPTY_TREE, '/data');
    tree = withEntries(tree, '/data', [dir('lights')]);
    tree = withLoading(toggleExpanded(tree, '/data/lights'), '/data/lights');
    const rows = flattenTree(tree);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ expanded: true, loaded: false, loading: true });
  });

  it('a file is never expanded, even if its path lingers in the set', () => {
    const tree = toggleExpanded(sample(), '/data/notes.txt');
    expect(flattenTree(tree).at(-1)?.expanded).toBe(false);
  });
});

describe('pendingPaths', () => {
  it('only asks for what is visible, expanded, neither loaded nor in flight', () => {
    let tree = withRoot(EMPTY_TREE, '/data');
    tree = withEntries(tree, '/data', [dir('lights'), dir('darks')]);
    expect(pendingPaths(flattenTree(tree))).toEqual([]);

    tree = toggleExpanded(tree, '/data/lights');
    expect(pendingPaths(flattenTree(tree))).toEqual(['/data/lights']);

    // marked in flight: the effect must not re-issue the same call on the next render
    tree = withLoading(tree, '/data/lights');
    expect(pendingPaths(flattenTree(tree))).toEqual([]);

    // arrived: nothing left to ask for, and the contents appear
    tree = withEntries(tree, '/data/lights', [file('sub.fits')]);
    expect(pendingPaths(flattenTree(tree))).toEqual([]);
    expect(names(tree)).toContain('sub.fits');
  });

  it('ignores an expanded branch hidden under a collapsed parent — nobody is looking at it', () => {
    let tree = withRoot(EMPTY_TREE, '/data');
    tree = withEntries(tree, '/data', [dir('lights')]);
    tree = withEntries(tree, '/data/lights', [dir('L')]);
    tree = toggleExpanded(toggleExpanded(tree, '/data/lights'), '/data/lights/L');
    expect(pendingPaths(flattenTree(tree))).toEqual(['/data/lights/L']);

    tree = toggleExpanded(tree, '/data/lights'); // collapse the parent
    expect(pendingPaths(flattenTree(tree))).toEqual([]);
  });
});

describe('collapsing', () => {
  it('hides descendants without losing their state: reopening finds the whole branch', () => {
    let tree = toggleExpanded(sample(), '/data/lights');
    tree = toggleExpanded(tree, '/data/lights/L');
    const expandedNames = names(tree);

    tree = toggleExpanded(tree, '/data/lights');
    expect(names(tree)).toEqual(['lights', 'darks', 'notes.txt']);
    // the grandchild's state survives its parent being collapsed…
    expect(tree.expanded.has('/data/lights/L')).toBe(true);

    tree = toggleExpanded(tree, '/data/lights');
    expect(names(tree)).toEqual(expandedNames); // …and reopening restores the tree as it was
    expect(pendingPaths(flattenTree(tree))).toEqual([]); // without a single server call
  });
});

describe('read failure', () => {
  it('collapses the folder: leaving it open and empty would re-issue the call every render', () => {
    let tree = withRoot(EMPTY_TREE, '/data');
    tree = withEntries(tree, '/data', [dir('root-only')]);
    tree = withLoading(toggleExpanded(tree, '/data/root-only'), '/data/root-only');
    tree = withFailure(tree, '/data/root-only');
    expect(flattenTree(tree)).toHaveLength(1);
    expect(flattenTree(tree)[0]).toMatchObject({ expanded: false, loading: false });
    expect(pendingPaths(flattenTree(tree))).toEqual([]);
  });
});

describe('root', () => {
  it('changing root resets cache and expansions — they described somewhere else', () => {
    const tree = withRoot(toggleExpanded(sample(), '/data/lights'), '/other');
    expect(tree.root).toBe('/other');
    expect(tree.entries.size).toBe(0);
    expect(tree.expanded.size).toBe(0);
    expect(flattenTree(tree)).toEqual([]);
  });

  it('setting the same root again costs nothing — else a render would reset it endlessly', () => {
    const tree = toggleExpanded(sample(), '/data/lights');
    expect(withRoot(tree, '/data')).toBe(tree);
  });

  it('invalidation empties the cache and keeps expansions: that is the hidden-files toggle', () => {
    const tree = invalidate(toggleExpanded(sample(), '/data/lights'));
    expect(tree.root).toBe('/data');
    expect(tree.entries.size).toBe(0);
    expect(tree.expanded.has('/data/lights')).toBe(true);
    // once the root is reloaded, the open branch asks for itself again
    const reloaded = withEntries(tree, '/data', [dir('lights')]);
    expect(pendingPaths(flattenTree(reloaded))).toEqual(['/data/lights']);
  });
});

describe('immutability', () => {
  it('every gesture yields a new tree — a `useState` would not see a mutation', () => {
    const before = sample();
    const after = toggleExpanded(before, '/data/lights');
    expect(after).not.toBe(before);
    expect(before.expanded.size).toBe(0);
    expect(withLoading(after, '/data/lights').loading.has('/data/lights')).toBe(true);
    expect(after.loading.size).toBe(0);
  });
});
