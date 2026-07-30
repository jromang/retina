// Library — named instances and recipes, persisted on the server side.
//
// This is the counterpart of "process icons": a setting that works is set aside, found again
// the following week, and dragged onto a view. The storage (one XML per entry) already exists
// in the domain; this panel is only a view onto it.

import { useEffect, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import {
  carriesAnything,
  pythonSourceFor,
  readDragPayload,
  setDragImage,
  setDragPayload,
  type DragPayload,
} from '../dnd/dnd';
import { openContainerFromLibrary } from '../pipeline/containerEdit';
import { promptText } from '../ui/prompts';
import { useTreeNav } from '../ui/treeNav';

export interface LibraryEntry {
  name: string;
  kind: 'instance' | 'container';
  position: [number, number] | null;
  process_id?: string;
  process_ids?: string[];
}

/** Reloaded on `library.changed` — it lives on disk, outside the snapshot. */
export function useLibrary(): [LibraryEntry[], () => void] {
  const [entries, setEntries] = useState<LibraryEntry[]>([]);

  const reload = () => {
    void client
      .call<LibraryEntry[]>('library.list')
      .then(setEntries)
      .catch(() => undefined); // offline: the transition to `open` will replay the call
  };

  useEffect(() => {
    // A component mounted before the WebSocket opens would see its first call fail. So we
    // subscribe to the connection state rather than calling once and hoping.
    const unsubscribeState = client.onStateChange((state) => {
      if (state === 'open') reload();
    });
    const unsubscribeNotify = client.onNotification((method) => {
      if (method === 'library.changed') reload();
    });
    reload(); // already connected (a panel remounting): no pointless wait
    return () => {
      unsubscribeState();
      unsubscribeNotify();
    };
  }, []);

  return [entries, reload];
}

/** Load an entry's content then start a drag — used by the list AND by the Desktop. */
export async function startEntryDrag(
  transfer: DataTransfer,
  entry: LibraryEntry,
): Promise<void> {
  const detail = await client.call<{ kind: string; processes: DragPayload['processes'] }>(
    'library.get',
    { name: entry.name },
  );
  const payload: DragPayload = {
    kind: entry.kind,
    processes: detail.processes,
    // A library entry is never global: global processes are not filed away (they target no
    // view). We stay conservative rather than going to check.
    isGlobal: false,
    name: entry.name,
  };
  setDragPayload(transfer, payload, pythonSourceFor(payload));
  setDragImage(transfer, entry.name);
}

/** Ask for a name then save the dropped payload. */
export function storeDroppedPayload(payload: DragPayload, suggested: string): void {
  void promptText(m.panel_library_entry_name(), suggested, m.prompt_save()).then((name) => {
    if (!name) return;
    void client
      .call('library.put', { name, processes: payload.processes })
      .catch((error: unknown) => console.error(error));
  });
}

export function LibraryPanel() {
  const [entries] = useLibrary();
  const [over, setOver] = useState(false);

  // A recipe opens in its editor, an instance in its form: double-click and Enter share this
  // gesture — the panel had until now been unreachable from the keyboard.
  const openEntry = (entry: LibraryEntry) => {
    if (entry.kind === 'container') {
      void openContainerFromLibrary(entry.name).catch((e: unknown) => console.error(e));
    } else if (entry.process_id) {
      void client
        .call('layout.open_process', { process_id: entry.process_id })
        .catch(() => undefined);
    }
  };

  const nav = useTreeNav({
    idPrefix: 'library-tree',
    label: m.panel_tree_library(),
    items: entries.map((entry) => ({ id: entry.name })),
    onActivate: (index) => {
      const entry = entries[index];
      if (entry) openEntry(entry);
    },
  });

  const onDrop = (event: DragEvent) => {
    setOver(false);
    const transfer = event.dataTransfer;
    if (!transfer) return;
    event.preventDefault();
    const payload = readDragPayload(transfer);
    if (!payload) return;
    storeDroppedPayload(payload, payload.processes[0]?.process_id ?? 'instance');
  };

  return (
    <div
      {...nav.containerProps}
      style={{
        minHeight: '100%',
        outline: over ? '1px dashed var(--retina-drop-legal)' : 'none',
        outlineOffset: '-2px',
      }}
      onDragOver={(event) => {
        const transfer = (event as DragEvent).dataTransfer;
        if (!transfer || !carriesAnything(transfer)) return;
        event.preventDefault();
        transfer.dropEffect = 'copy';
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      {entries.length === 0 && (
        <p
          style={{
            color: 'var(--vscode-descriptionForeground)',
            fontSize: '12px',
            padding: '8px 12px',
            margin: 0,
          }}
        >
          {m.panel_library_empty()}
        </p>
      )}
      {entries.map((entry, index) => (
        <div
          key={entry.name}
          class="tree-row"
          {...nav.itemProps(index)}
          draggable
          title={
            entry.kind === 'container'
              ? (entry.process_ids ?? []).join(' → ')
              : entry.process_id
          }
          onDragStart={(event) => {
            const transfer = (event as DragEvent).dataTransfer;
            if (transfer) void startEntryDrag(transfer, entry);
          }}
          onClick={() => nav.setActiveIndex(index)}
          onDblClick={() => openEntry(entry)}
        >
          <i
            class={`codicon codicon-${entry.kind === 'container' ? 'list-ordered' : 'symbol-method'}`}
            aria-hidden="true"
          />
          <span>{entry.name}</span>
          <span style={{ flex: 1 }} />
          <button
            title={m.prompt_delete()}
            onClick={(event) => {
              event.stopPropagation();
              void client.call('library.delete', { name: entry.name }).catch(() => undefined);
            }}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--vscode-descriptionForeground)',
              cursor: 'pointer',
            }}
          >
            <i class="codicon codicon-trash" aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
}
