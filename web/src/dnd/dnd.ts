// Drag-and-drop of process instances.
//
// The signature gesture of this class of application: an instance is dragged from a form's ⠿
// handle (or from the Library, or the Desktop) and dropped onto a view. The target is the
// smallest preview under the cursor, otherwise the whole image.
//
// # The MIME type that has no equivalent in a desktop toolkit
//
// In HTML5, `dragover` gives access only to the **types** of the transfer, never to the data —
// a browser anti-leak measure. It is therefore impossible to read the instance in order to
// decide whether the drop is legal. Legality must instead be encoded in the type itself, hence
// `application/x-retina-process-global`: since a global process has no target view, the
// viewport refuses that type on hover, without having to decode anything.
//
// `text/plain` carries the equivalent Python code: dropping an instance into the console, or
// into any text editor, yields an executable line. That is kept as is.

export const MIME_PROCESS = 'application/x-retina-process';
export const MIME_PROCESS_GLOBAL = 'application/x-retina-process-global';
export const MIME_CONTAINER = 'application/x-retina-container';
/**
 * A file **path**, dragged from the explorer.
 *
 * A type distinct from the other three, for the same reason as they are: `dragover` gives
 * access only to the *types* of the transfer, never to the data. The viewport must decide
 * whether it accepts the hover without decoding anything — and "open a file" is not "apply a
 * process to this view".
 */
export const MIME_FILE = 'application/x-retina-file';

export interface ProcessPayload {
  process_id: string;
  values: Record<string, unknown>;
}

export interface DragPayload {
  kind: 'instance' | 'container';
  processes: ProcessPayload[];
  isGlobal: boolean;
  /** Name of the library entry, if the drag comes from one. */
  name?: string;
}

/** Writes the payload into a `dragstart`, in the three expected forms. */
export function setDragPayload(
  transfer: DataTransfer,
  payload: DragPayload,
  pythonSource: string,
): void {
  const json = JSON.stringify(payload);
  if (payload.kind === 'container') {
    transfer.setData(MIME_CONTAINER, json);
  } else {
    transfer.setData(payload.isGlobal ? MIME_PROCESS_GLOBAL : MIME_PROCESS, json);
  }
  transfer.setData('text/plain', pythonSource);
  transfer.effectAllowed = 'copyMove';
}

/**
 * Starts the drag of a file. `text/plain` carries the bare path: dropping it into the console
 * or any text field writes the path there, which is exactly what one wants while writing a
 * script.
 */
export function setFileDrag(transfer: DataTransfer, path: string): void {
  transfer.setData(MIME_FILE, path);
  transfer.setData('text/plain', path);
  transfer.effectAllowed = 'copy';
}

/** Does the transfer carry a file path? (readable in `dragover`) */
export function carriesFile(transfer: DataTransfer): boolean {
  return transfer.types.includes(MIME_FILE);
}

export function readFilePath(transfer: DataTransfer): string | null {
  return transfer.getData(MIME_FILE) || null;
}

export function readDragPayload(transfer: DataTransfer): DragPayload | null {
  for (const type of [MIME_PROCESS, MIME_PROCESS_GLOBAL, MIME_CONTAINER]) {
    const raw = transfer.getData(type);
    if (raw) {
      try {
        return JSON.parse(raw) as DragPayload;
      } catch {
        return null;
      }
    }
  }
  return null;
}

/** Does the transfer carry an instance applicable to a view? (readable in `dragover`) */
export function carriesApplicable(transfer: DataTransfer): boolean {
  return (
    transfer.types.includes(MIME_PROCESS) || transfer.types.includes(MIME_CONTAINER)
  );
}

/** Does the transfer carry a global process, which cannot target a view? */
export function carriesGlobal(transfer: DataTransfer): boolean {
  return transfer.types.includes(MIME_PROCESS_GLOBAL);
}

export function carriesAnything(transfer: DataTransfer): boolean {
  return carriesApplicable(transfer) || carriesGlobal(transfer);
}

/**
 * The equivalent Python, on **one** line — droppable into the console or an editor.
 *
 * For an instance, it is word for word what the execution will echo. For a recipe, the domain
 * echo (`ProcessContainer.to_python_source`) takes the long form: an import, a `pc =`, one
 * `pc.add(...)` per step. Same effect, different form — and deliberately so, the long form
 * would not fit in a drag-and-drop transfer.
 */
export function pythonSourceFor(payload: DragPayload, target = 'app.active_view'): string {
  const call = (process: ProcessPayload) => {
    const args = Object.entries(process.values)
      .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
      .join(', ');
    return `${process.process_id}(${args})`;
  };
  if (payload.kind === 'container') {
    const items = payload.processes.map(call).join(', ');
    return `ProcessContainer([${items}]).execute_on(${target})`;
  }
  const only = payload.processes[0];
  return only ? `${call(only)}.execute_on(${target})` : '';
}

/**
 * Drag image: a readable badge rather than a snapshot of the source button.
 *
 * The element must be in the document at call time — the browser takes a snapshot of it, and it
 * is removed on the next tick.
 */
export function setDragImage(transfer: DataTransfer, label: string): void {
  const ghost = document.createElement('div');
  ghost.textContent = label;
  ghost.style.cssText = `
    position: fixed; top: -1000px; left: -1000px;
    padding: 4px 10px; border-radius: 3px;
    background: var(--vscode-editorWidget-background);
    border: 1px solid var(--retina-drop-legal);
    color: var(--vscode-foreground);
    font: 12px var(--retina-font-ui); white-space: nowrap;
  `;
  document.body.appendChild(ghost);
  transfer.setDragImage(ghost, 8, 8);
  setTimeout(() => ghost.remove(), 0);
}
