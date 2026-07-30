// Tree model of the file explorer — pure, hence testable without a DOM.
//
// The server can only return one folder at a time (`fs.list`), and that is deliberate: a
// recursive `fs.tree` over a home folder of 100,000 files would make the first display pay
// dearly, for branches nobody will open. The tree is therefore **built by the client** — one
// expansion = one call — and this file holds the three states that follow from it: what is
// loaded, what is expanded, what is in flight.
//
// Everything is **immutable**: each function returns a new tree (or the same one, if nothing
// changes). That is what lets the panel keep it in a `useState` without having to decide when
// to re-render — and it is also what makes the tests readable.
//
// The order of the entries is **never** touched up: `fs.list` already returns directories
// first then alphabetical order. Re-sorting here means condemning ourselves to diverge from
// the server the day its rule changes.

export interface FileEntry {
  name: string;
  is_dir: boolean;
  size: number;
  mtime: number;
}

/** Reply of `fs.list` — the folder read, its parent, its content. */
export interface FileListing {
  path: string;
  parent: string | null;
  entries: FileEntry[];
}

export interface FileTree {
  /** Folder shown at the root of the tree — `null` until the server has said which. */
  readonly root: string | null;
  /** Known content, by folder path. Absent = never loaded. */
  readonly entries: ReadonlyMap<string, readonly FileEntry[]>;
  /** Expanded folders — a path stays in there when an ancestor collapses. */
  readonly expanded: ReadonlySet<string>;
  /** Folders whose `fs.list` is in flight. */
  readonly loading: ReadonlySet<string>;
}

/** One visible row of the flattened tree. */
export interface TreeRow {
  readonly path: string;
  readonly entry: FileEntry;
  /** 0 = direct child of the root. `aria-level` equals `depth + 1`. */
  readonly depth: number;
  readonly expanded: boolean;
  readonly loaded: boolean;
  readonly loading: boolean;
}

export const EMPTY_TREE: FileTree = {
  root: null,
  entries: new Map(),
  expanded: new Set(),
  loading: new Set(),
};

/**
 * Concatenate a name onto a folder.
 *
 * The separator is deduced from the path rather than from the browser: the disk being read is
 * the **server's**, which may be a Windows machine driven from a Linux browser.
 */
export function joinPath(directory: string, name: string): string {
  const separator = directory.includes('\\') && !directory.includes('/') ? '\\' : '/';
  return directory.endsWith(separator) ? `${directory}${name}` : `${directory}${separator}${name}`;
}

/**
 * Set the root. Changing root **resets** everything: an expansion remembered from another
 * root no longer means anything, and keeping it would reopen unrelated branches.
 */
export function withRoot(tree: FileTree, root: string): FileTree {
  if (tree.root === root) return tree;
  return { ...EMPTY_TREE, root };
}

/** Record a folder's content — which ends its loading. */
export function withEntries(
  tree: FileTree,
  path: string,
  entries: readonly FileEntry[],
): FileTree {
  const next = new Map(tree.entries);
  next.set(path, entries);
  return { ...tree, entries: next, loading: without(tree.loading, path) };
}

/** Mark a folder as loading (avoids issuing the same call twice). */
export function withLoading(tree: FileTree, path: string): FileTree {
  if (tree.loading.has(path)) return tree;
  return { ...tree, loading: with_(tree.loading, path) };
}

/**
 * Failure to read a folder (permissions, mount gone): it is **collapsed**.
 *
 * Leaving it expanded and empty would restart the call on every render, and would show a
 * folder opened onto nothing — two ways of lying. Collapsed, a second click retries,
 * deliberately.
 */
export function withFailure(tree: FileTree, path: string): FileTree {
  return {
    ...tree,
    expanded: without(tree.expanded, path),
    loading: without(tree.loading, path),
  };
}

/**
 * Expand/collapse a folder.
 *
 * Collapsing touches **only** that path: the descendants keep their expansion state (and
 * their cached content), so that reopening a branch finds it exactly as it was left, without
 * a single server call.
 */
export function toggleExpanded(tree: FileTree, path: string): FileTree {
  return {
    ...tree,
    expanded: tree.expanded.has(path) ? without(tree.expanded, path) : with_(tree.expanded, path),
  };
}

/**
 * Empty the cache while keeping the expansions — this is the gesture of the hidden-files
 * toggle (every listing becomes wrong) and of a manual refresh. The open branches then
 * reload by themselves, through `pendingPaths`.
 */
export function invalidate(tree: FileTree): FileTree {
  return { ...tree, entries: new Map(), loading: new Set() };
}

/**
 * Ordered list of the visible rows.
 *
 * We only descend into folders that are **expanded and loaded**: an expanded folder whose
 * content has not arrived yet yields its row (with its state) and nothing else. That is also
 * what bounds the recursion — a circular symbolic link cannot loop, each level demanding an
 * explicit expansion hence a server call.
 */
export function flattenTree(tree: FileTree): TreeRow[] {
  const rows: TreeRow[] = [];
  if (tree.root === null) return rows;
  const walk = (directory: string, depth: number): void => {
    for (const entry of tree.entries.get(directory) ?? []) {
      const path = joinPath(directory, entry.name);
      const expanded = entry.is_dir && tree.expanded.has(path);
      rows.push({
        path,
        entry,
        depth,
        expanded,
        loaded: tree.entries.has(path),
        loading: tree.loading.has(path),
      });
      if (expanded && tree.entries.has(path)) walk(path, depth + 1);
    }
  };
  walk(tree.root, 0);
  return rows;
}

/**
 * Folders to ask the server for: expanded, visible, neither loaded nor in flight.
 *
 * The computation starts from the **visible** rows and not from the `expanded` set: a branch
 * buried under a collapsed parent has no reason to be loaded, and an expansion inherited from
 * an abandoned root does not show up at all.
 */
export function pendingPaths(rows: readonly TreeRow[]): string[] {
  return rows
    .filter((row) => row.entry.is_dir && row.expanded && !row.loaded && !row.loading)
    .map((row) => row.path);
}

function with_<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  next.add(value);
  return next;
}

function without<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  next.delete(value);
  return next;
}
