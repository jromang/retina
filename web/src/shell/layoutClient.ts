// Layout state on the client side, and its reconciliation with the Python mirror.
//
// The server keeps a mirror so as to answer `app.layout.is_visible(...)` synchronously
// from the console (see server/layout_backend.py). This module is the other half of the contract:
//
//   server → client: `layout.command` notification (the user typed a command, or
//                    a script did) → we apply it.
//   client → server: `layout.report` as soon as anything is changed with the mouse → the
//                    Python mirror stays correct, otherwise the console would lie.
//
// The actions triggered by the UI do NOT go through this module: they call
// `layout.activate` & co. as RPCs, which routes them through `app.layout` — hence with a Python
// echo. The `layout.command` that comes back is then a confirmation we apply
// idempotently.

import { batch, computed, signal } from '@preact/signals';

import { client } from '../api/client';
import { applyZoneSizes, zoneSizes, type ZoneSizes } from './zoneSizes';
import {
  BUILTIN_PERSPECTIVES,
  DEFAULT_VISIBLE,
  PANELS,
  PERSPECTIVE_LAYOUTS,
  SIDEBAR_PANELS,
  ZONE_PANELS,
  ZONES,
  type BuiltinPerspective,
  type PanelId,
  type ZoneId,
} from './panels';

/**
 * Keeps only the panel ids that still exist.
 *
 * A perspective saved on the user's disk survives the removal of a panel — the
 * "Journal" deleted in July 2026 still sleeps in the files of the previous version.
 * Without this filter, its dead key came back into `panelVisible` and left again as is on the
 * next `layout.report`: the server threw it away (it already filters), but the client mirror
 * carried a ghost state that nothing rendered.
 */
function knownPanels(
  visible: Partial<Record<PanelId, boolean>>,
): Partial<Record<PanelId, boolean>> {
  return Object.fromEntries(
    Object.entries(visible).filter(([panel]) => (PANELS as readonly string[]).includes(panel)),
  ) as Partial<Record<PanelId, boolean>>;
}

export const panelVisible = signal<Record<PanelId, boolean>>({ ...DEFAULT_VISIBLE });
export const layoutLocked = signal(false);
export const openProcesses = signal<readonly string[]>([]);
/**
 * Starting values of a form, laid down by `app.layout.open_process(id, values)`.
 *
 * They only live long enough to be consumed by the panel: keeping them would replay them on
 * every reconnection and would erase the settings the user has made since.
 */
export const seededValues = signal<Readonly<Record<string, Record<string, unknown>>>>({});

/** Reads and clears the starting values of a process. */
export function takeSeed(processId: string): Record<string, unknown> | null {
  const seed = seededValues.value[processId];
  if (!seed) return null;
  const { [processId]: _used, ...rest } = seededValues.value;
  seededValues.value = rest;
  return seed;
}
/** Perspective to save: the server asked, we must answer with our state. */
export const pendingSave = signal<string | null>(null);

export const activeSidebarPanel = computed<PanelId | null>(
  () => SIDEBAR_PANELS.find((panel) => panelVisible.value[panel]) ?? null,
);

/**
 * Visibility of the zones — **derived**, exactly as on the Python side.
 *
 * Making it a signal of its own would create a second state to reconcile for the same information.
 */
export const zoneVisible = computed<Record<ZoneId, boolean>>(() => {
  const visible = panelVisible.value;
  return Object.fromEntries(
    ZONES.map((zone) => [zone, ZONE_PANELS[zone].some((panel) => visible[panel])]),
  ) as Record<ZoneId, boolean>;
});

interface LayoutCommand {
  op: string;
  panel?: PanelId;
  visible?: boolean;
  name?: string;
  locked?: boolean;
  process_id?: string;
  /** `open_process`: starting values of the form. */
  values?: Record<string, unknown>;
  layout?: unknown;
  zone?: ZoneId;
  /** For `set_zone_visible`: the panels to leave open, already resolved by the server. */
  panels?: PanelId[];
}

function setVisible(panel: PanelId, visible: boolean): void {
  panelVisible.value = { ...panelVisible.value, [panel]: visible };
}

function activate(panel: PanelId): void {
  if (!SIDEBAR_PANELS.includes(panel)) {
    setVisible(panel, true);
    return;
  }
  // Sidebar exclusivity, applied here *and* on the Python side: the two mirrors
  // must end up in the same state without talking to each other.
  const next = { ...panelVisible.value };
  for (const other of SIDEBAR_PANELS) next[other] = other === panel;
  panelVisible.value = next;
}

function applyPerspective(name: string): void {
  const layout = PERSPECTIVE_LAYOUTS[name as BuiltinPerspective];
  if (layout) panelVisible.value = { ...layout };
}

/** Exported for vitest: this is the entry point of everything the server pushes at us. */
export function applyCommand(command: LayoutCommand): void {
  switch (command.op) {
    case 'set_visible':
      if (command.panel) setVisible(command.panel, command.visible ?? false);
      break;
    case 'set_zone_visible': {
      // The server sends the resolved list (it holds the memory of the last active panel):
      // we apply it, without replaying its logic.
      if (!command.zone) break;
      const wanted = command.panels ?? [];
      const next = { ...panelVisible.value };
      for (const panel of ZONE_PANELS[command.zone]) next[panel] = wanted.includes(panel);
      panelVisible.value = next;
      break;
    }
    case 'activate':
      if (command.panel) activate(command.panel);
      break;
    case 'reset':
      panelVisible.value = { ...DEFAULT_VISIBLE };
      break;
    case 'set_locked':
      layoutLocked.value = command.locked ?? false;
      break;
    case 'load_builtin':
      if (command.name) applyPerspective(command.name);
      break;
    case 'load_perspective':
      applyStoredLayout(command.layout);
      break;
    case 'request_save':
      pendingSave.value = command.name ?? null;
      break;
    case 'open_process':
      if (!command.process_id) break;
      if (command.values) {
        seededValues.value = { ...seededValues.value, [command.process_id]: command.values };
      }
      if (!openProcesses.value.includes(command.process_id)) {
        openProcesses.value = [...openProcesses.value, command.process_id];
      }
      break;
    case 'close_process':
      openProcesses.value = openProcesses.value.filter((id) => id !== command.process_id);
      break;
    default:
      console.warn('commande de layout inconnue', command);
  }
}

interface StoredLayout {
  visible?: Partial<Record<PanelId, boolean>>;
  /** Sizes of the zones. **Optional** field: the perspectives already saved, which do not
   *  carry it, must keep reading back without conversion. */
  sizes?: Partial<ZoneSizes>;
}

function applyStoredLayout(blob: unknown): void {
  const stored = blob as StoredLayout | null;
  if (!stored) return;
  if (stored.visible) panelVisible.value = { ...DEFAULT_VISIBLE, ...knownPanels(stored.visible) };
  if (stored.sizes) applyZoneSizes(stored.sizes);
}

/**
 * Serializes the current layout — payload of `layout.store_perspective`.
 *
 * The zone sizes are part of it: they used to live in a `useState` of
 * `Workbench`, so that a saved perspective only restored the *visibility* of the
 * panels, never their width.
 */
export function serializeLayout(): StoredLayout {
  return { visible: { ...panelVisible.value }, sizes: { ...zoneSizes.value } };
}

/** Declares the real state to the server. To be called after any mouse manipulation. */
export function reportLayout(): void {
  void client
    .call('layout.report', {
      visible: panelVisible.value,
      open_processes: [...openProcesses.value],
    })
    .catch(() => undefined);
}

/** User action: goes through `app.layout` so as to produce the Python echo. */
export function requestActivate(panel: PanelId): void {
  void client.call('layout.activate', { panel }).catch((e: unknown) => console.error(e));
}

export function requestToggle(panel: PanelId): void {
  void client.call('layout.toggle', { panel }).catch((e: unknown) => console.error(e));
}

/** Collapses/expands a whole zone. The server remembers the panels to reopen. */
export function requestToggleZone(zone: ZoneId): void {
  void client.call('layout.toggle_zone', { zone }).catch((e: unknown) => console.error(e));
}

export function requestPerspective(name: string): void {
  void client.call('layout.load', { name }).catch((e: unknown) => console.error(e));
}

export function requestCloseProcess(processId: string): void {
  void client
    .call('layout.close_process', { process_id: processId })
    .catch((e: unknown) => console.error(e));
}

export function connectLayout(): void {
  client.onNotification((method, params) => {
    if (method === 'layout.command') applyCommand(params as LayoutCommand);
  });

  // Answers `request_save`: the server does not know the layout, we do.
  pendingSave.subscribe((name) => {
    if (!name) return;
    const blob = serializeLayout();
    batch(() => {
      pendingSave.value = null;
    });
    void client
      .call('layout.store_perspective', { name, layout: blob })
      .catch((e: unknown) => console.error(e));
  });

}

/**
 * Adopts the layout announced by the server at the `hello`.
 *
 * The direction matters: it is the server that survives connections, and a script may have set
 * the layout before the interface opens. Reporting our defaults on connection — which
 * the first version did — silently erased that setting.
 */
export function adoptLayout(state: {
  visible: Partial<Record<PanelId, boolean>>;
  locked: boolean;
  open_processes: string[];
}): void {
  batch(() => {
    panelVisible.value = { ...DEFAULT_VISIBLE, ...knownPanels(state.visible) };
    layoutLocked.value = state.locked;
    openProcesses.value = state.open_processes;
  });
}

export { BUILTIN_PERSPECTIVES };
