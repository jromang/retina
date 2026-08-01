// File explorer — browsing the **server's** disk.
//
// It really is the server's disk that matters, not the browser's: `app.open(path)` reads a
// FITS where Python runs, and `app.run_recipe` executes its scripts there. In browser or
// remote mode, an HTML picker would show the wrong disk — and would hide the path, which is
// precisely what is needed.
//
// The API first, the panel second (same order as the FITS header panel): everything that
// follows leans on the `fs.*` family, which adds no privilege — the console already gives the
// whole file system — but types and bounds it.
//
// **Expandable tree, lazily expanded.** Folder-by-folder navigation was enough to open an
// isolated exposure; it is no longer enough for a real project, where one compares one night's
// raw frames with another night's masters and where descending and climbing back loses the
// thread. A single mode, and that is what keeps the thing small: **fully collapsed, the tree
// is exactly the old flat list**. The model lives in `fileTree.ts` (pure, tested); what is
// left here is only the rendering and the calls. The server has not moved: one expansion =
// one `fs.list`, never a recursive walk — a home folder of 100,000 files would make the first
// display pay for it.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import { setDragImage, setFileDrag } from '../dnd/dnd';
import { openScriptFromDisk } from '../scripts/scripts';
import { filesRoot, setFilesRoot } from './filesRoot';
import { isReadableImage } from '../api/formats';
import { askPath } from '../shell/native';
import { useTreeNav } from '../ui/treeNav';
import { rowWindow } from './processRows';
import {
  EMPTY_TREE,
  type FileEntry,
  type FileListing,
  type FileTree,
  type TreeRow,
  flattenTree,
  invalidate,
  pendingPaths,
  toggleExpanded,
  withEntries,
  withFailure,
  withLoading,
  withRoot,
} from './fileTree';

const MUTED = 'var(--vscode-descriptionForeground)';
/** Height imposed on rows: arithmetic windowing demands a known height. */
const ROW_HEIGHT = 22;
/** Horizontal offset per depth level. */
const INDENT = 12;

/** Readable size — the server returns bytes, nobody counts in bytes. */
function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} ${m.panel_files_unit_b()}`;
  const units = [
    m.panel_files_unit_kb(),
    m.panel_files_unit_mb(),
    m.panel_files_unit_gb(),
    m.panel_files_unit_tb(),
  ];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

/** Short, locale-aware date — `mtime` arrives in Unix seconds. */
function humanDate(mtime: number): string {
  return new Date(mtime * 1000).toLocaleDateString(undefined, {
    year: '2-digit',
    month: '2-digit',
    day: '2-digit',
  });
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot < 0 ? '' : name.slice(dot + 1).toLowerCase();
}

function iconFor(entry: FileEntry, expanded: boolean): string {
  if (entry.is_dir) return expanded ? 'folder-opened' : 'folder';
  if (isReadableImage(entry.name)) return 'file-media';
  if (extensionOf(entry.name) === 'py') return 'file-code';
  return 'file';
}

export function FilesPanel() {
  // The root lives in a module signal (`filesRoot`) and not here: opening a project must be
  // able to set it while this panel is perhaps not even mounted.
  const root = filesRoot.value;
  const [tree, setTree] = useState<FileTree>(EMPTY_TREE);
  const [parent, setParent] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [hidden, setHidden] = useState(false);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(600);
  const scrollerRef = useRef<HTMLDivElement>(null);
  // Generation: a new root or a toggle of the hidden files makes in-flight replies obsolete.
  // We let them come back and then drop them, rather than building a cancellation protocol
  // for calls that cost one `readdir`.
  const generation = useRef(0);
  const lastHidden = useRef(hidden);

  const fail = (exception: unknown) =>
    setError(exception instanceof Error ? exception.message : String(exception));

  // (1) The root. `root` null → the server answers with *its* home folder: the client cannot
  // guess it, and guessing it from the browser would give the wrong disk.
  useEffect(() => {
    generation.current += 1;
    // Only the hidden-files toggle expires the cache — and it expires it *entirely*, open
    // branches included, which then reload by themselves through (2). A change of root is
    // already reset by `withRoot` when the reply arrives: clearing here would only blank the
    // panel for the duration of the round trip.
    if (lastHidden.current !== hidden) {
      lastHidden.current = hidden;
      setTree(invalidate);
    }
    const mine = generation.current;
    void client
      .call<FileListing>('fs.list', root === null ? { hidden } : { path: root, hidden })
      .then((result) => {
        if (generation.current !== mine) return;
        setError('');
        setParent(result.parent);
        setTree((current) =>
          withEntries(withRoot(current, result.path), result.path, result.entries),
        );
        if (result.path !== root) setFilesRoot(result.path);
      })
      .catch((exception: unknown) => {
        if (generation.current !== mine) return;
        fail(exception);
        // Folder gone or become unreadable: fall back on the home folder rather than leave
        // an empty panel with nothing to say how to get out of it.
        if (root !== null) setFilesRoot(null);
      });
  }, [root, hidden]);

  const rows = flattenTree(tree);
  const pending = pendingPaths(rows);
  // Dependency key: the list's content, not its array identity — recomputed on every render,
  // it would restart the effect indefinitely.
  const pendingKey = pending.join('\n');

  // (2) The branches expanded and not yet loaded. An effect rather than a call in the click
  // handler: expansion is not the only path that leaves a branch to load (invalidation, state
  // restoration), and a single call site cannot drift.
  useEffect(() => {
    if (pending.length === 0) return;
    const mine = generation.current;
    setTree((current) => pending.reduce((acc, path) => withLoading(acc, path), current));
    for (const path of pending) {
      void client
        .call<FileListing>('fs.list', { path, hidden })
        .then((result) => {
          if (generation.current !== mine) return;
          setTree((current) => withEntries(current, path, result.entries));
        })
        .catch((exception: unknown) => {
          if (generation.current !== mine) return;
          fail(exception);
          setTree((current) => withFailure(current, path));
        });
    }
  }, [pendingKey, hidden]);

  const toggle = (row: TreeRow) => setTree((current) => toggleExpanded(current, row.path));

  const open = (row: TreeRow) => {
    // A folder expands in place. Descending *into* a folder is still possible — that is the
    // root selector's job — but it is no longer the default gesture: the whole point of the
    // tree is precisely to see two branches at once.
    if (row.entry.is_dir) {
      toggle(row);
      return;
    }
    if (isReadableImage(row.entry.name)) {
      // `app.open`, hence echoed: opening from this panel writes the same line as if it had
      // been typed in the console.
      void client.call('app.open', { path: row.path }).catch(fail);
    } else {
      // Any other extension opens **as text**. Silently doing nothing was the worst choice:
      // a double-click with no effect does not say whether the format is refused or whether
      // the gesture missed. A recipe `.xml` or a notes `.txt` therefore opens, read-only.
      void openScriptFromDisk(row.path).catch(fail);
    }
  };

  const { start, end } = rowWindow(scrollTop, viewportHeight, rows.length, ROW_HEIGHT);

  const nav = useTreeNav({
    idPrefix: 'files-tree',
    label: m.panel_tree_files(),
    // `level` is what gives `treeNav` its ←/→: parent and first child are deduced from it.
    items: rows.map((row) => ({ id: row.path, level: row.depth + 1 })),
    onActivate: (index) => {
      const row = rows[index];
      if (row) open(row);
    },
    // windowing: the targeted row may not be rendered — so move the scroll instead
    scrollIntoView: (index) => {
      const scroller = scrollerRef.current;
      if (!scroller) return;
      const top = index * ROW_HEIGHT;
      if (top < scroller.scrollTop) scroller.scrollTop = top;
      else if (top + ROW_HEIGHT > scroller.scrollTop + scroller.clientHeight) {
        scroller.scrollTop = top + ROW_HEIGHT - scroller.clientHeight;
      }
    },
  });

  // ←/→ on a folder: expand/collapse first, move second. That is the gesture of every tree,
  // and the only **keyboard** path to expansion; without it, `treeNav` would send the right
  // arrow of a closed folder into the void.
  const onKeyDown = (event: KeyboardEvent) => {
    const row = rows[nav.activeIndex];
    if (row?.entry.is_dir) {
      if (event.key === 'ArrowRight' && !row.expanded) {
        event.preventDefault();
        toggle(row);
        return;
      }
      if (event.key === 'ArrowLeft' && row.expanded) {
        event.preventDefault();
        toggle(row);
        return;
      }
    }
    nav.containerProps.onKeyDown(event);
  };

  // The visible height follows the panel (splitters, window) — measured, never guessed.
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const observer = new ResizeObserver(() => setViewportHeight(scroller.clientHeight));
    observer.observe(scroller);
    return () => observer.disconnect();
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '4px',
          padding: '4px 8px',
          borderBottom: '1px solid var(--vscode-panel-border)',
        }}
      >
        <button
          class="btn"
          title={m.panel_files_parent()}
          disabled={!parent}
          onClick={() => parent && setFilesRoot(parent)}
          style={{ padding: '0 6px' }}
        >
          <i class="codicon codicon-arrow-up" aria-hidden="true" />
        </button>
        <button
          class="btn"
          title={m.panel_files_choose_root()}
          onClick={() => {
            void askPath({ title: m.panel_files_working_folder(), folder: true }).then((paths) => {
              if (paths?.[0]) setFilesRoot(paths[0]);
            });
          }}
          style={{ padding: '0 6px' }}
        >
          <i class="codicon codicon-folder-opened" aria-hidden="true" />
        </button>
        {/* `fs.list` had accepted `hidden` since day one and the interface never sent it:
            the capability existed with no path to reach it. */}
        <button
          class="btn"
          title={hidden ? m.panel_files_hide_hidden() : m.panel_files_show_hidden()}
          aria-pressed={hidden}
          onClick={() => setHidden(!hidden)}
          style={{ padding: '0 6px', opacity: hidden ? 1 : 0.6 }}
        >
          <i class="codicon codicon-eye" aria-hidden="true" />
        </button>
        <span
          style={{
            flex: 1,
            fontSize: '11px',
            color: MUTED,
            direction: 'rtl',
            textAlign: 'left',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={tree.root ?? ''}
        >
          {tree.root ?? '…'}
        </span>
      </div>

      {error && (
        <p
          style={{
            margin: 0,
            padding: '6px 10px',
            fontSize: '12px',
            color: 'var(--vscode-errorForeground)',
          }}
        >
          {error}
        </p>
      )}

      <div
        ref={scrollerRef}
        {...nav.containerProps}
        onKeyDown={onKeyDown}
        data-focus-ring
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', outline: 'none' }}
        onScroll={(event) => setScrollTop((event.target as HTMLDivElement).scrollTop)}
      >
        {tree.root !== null && rows.length === 0 && (
          <p style={{ color: MUTED, fontSize: '12px', padding: '8px 12px', margin: 0 }}>
            {m.panel_files_empty()}
          </p>
        )}
        <div style={{ height: `${start * ROW_HEIGHT}px` }} />
        {rows.slice(start, end).map((row, offset) => {
          const index = start + offset;
          return (
            <div
              key={row.path}
              class="tree-row"
              {...nav.itemProps(index)}
              aria-expanded={row.entry.is_dir ? row.expanded : undefined}
              // Only files can be dragged: dropping a folder would make no sense here, and
              // offering it would give a gesture that fails.
              draggable={!row.entry.is_dir}
              title={row.entry.name}
              style={{
                height: `${ROW_HEIGHT}px`,
                paddingLeft: `${12 + row.depth * INDENT}px`,
              }}
              onDragStart={(event: DragEvent) => {
                if (!event.dataTransfer) return;
                setFileDrag(event.dataTransfer, row.path);
                setDragImage(event.dataTransfer, row.entry.name);
              }}
              onClick={() => nav.setActiveIndex(index)}
              onDblClick={() => open(row)}
            >
              {/* The chevron expands on a **single** click: that is the expected gesture of a
                  tree, and it leaves the double-click to opening. Files keep its gutter,
                  without which names at the same level would not line up. */}
              <span
                style={{ width: '14px', flex: '0 0 14px', textAlign: 'center' }}
                onClick={(event: MouseEvent) => {
                  if (!row.entry.is_dir) return;
                  event.stopPropagation();
                  nav.setActiveIndex(index);
                  toggle(row);
                }}
                onDblClick={(event: MouseEvent) => event.stopPropagation()}
              >
                {row.entry.is_dir && (
                  <i
                    class={
                      row.loading
                        ? 'codicon codicon-loading codicon-modifier-spin'
                        : `codicon codicon-chevron-${row.expanded ? 'down' : 'right'}`
                    }
                    aria-hidden="true"
                  />
                )}
              </span>
              <i class={`codicon codicon-${iconFor(row.entry, row.expanded)}`} aria-hidden="true" />
              <span
                style={{
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {row.entry.name}
              </span>
              {/* Size and date were returned by the server and shown nowhere. On a folder of
                  raw frames, they are the two columns one sorts by at a glance. */}
              {!row.entry.is_dir && (
                <span style={{ color: MUTED, fontSize: '10px', whiteSpace: 'nowrap' }}>
                  {humanSize(row.entry.size)}
                </span>
              )}
              <span style={{ color: MUTED, fontSize: '10px', whiteSpace: 'nowrap' }}>
                {humanDate(row.entry.mtime)}
              </span>
            </div>
          );
        })}
        <div style={{ height: `${Math.max(0, rows.length - end) * ROW_HEIGHT}px` }} />
      </div>
    </div>
  );
}
