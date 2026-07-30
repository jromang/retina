// Contract of the panels and the zones — TypeScript mirror of
// python/retina/server/layout_backend.py.
//
// These ids are **public**: a recipe writes `app.layout.activate('explorer')` verbatim. This is
// the kind of constant one is tempted to "modernize" along the way; do not do it.
//
// Corollary for i18n: the `title`s below are **labels**, translated, whereas
// the keys that carry them stay identifiers. `BUILTIN_PERSPECTIVES` is the borderline case —
// its three names are at once the argument of `app.layout.load('Processing')` and file
// names on the server side. So they are not translated in place: `perspectiveLabel` does the
// mapping, and translating the ids would break every perspective already saved.

import { m } from '../paraglide/messages';

export const PANELS = [
  'explorer',
  'files',
  'windows',
  'history',
  'library',
  'header',
  'stf',
  'doc',
  'home',
  'desktop',
  'pipeline',
  'settings',
  'credits',
  'selector',
  'lightcurve',
  'rtp',
  'console',
  'chat',
] as const;

export type PanelId = (typeof PANELS)[number];

/** Exclusive group of the sidebar: one visible at a time (the VS Code rule). */
export const SIDEBAR_PANELS: readonly PanelId[] = [
  'explorer',
  'files',
  'windows',
  'history',
  'library',
  'header',
];

/** Panels of the bottom zone, as tabs. */
export const BOTTOM_PANELS: readonly PanelId[] = ['console', 'rtp'];

/** Panels of the right zone (tools). */
export const RIGHT_PANELS: readonly PanelId[] = ['stf', 'chat'];

/**
 * The three collapsible **zones**. Same names as the CSS `grid-area`s and as the `data-*` of
 * `.workbench`: one vocabulary, from the CSS all the way to the Python console.
 *
 * A zone has no state of its own — it is visible as soon as one of its panels is. Collapsing
 * goes through `app.layout.toggle_zone`, on the server side, which remembers what has to be
 * reopened. Do not duplicate that memory here.
 */
export const ZONES = ['sidebar', 'bottom', 'right'] as const;
export type ZoneId = (typeof ZONES)[number];

export const ZONE_PANELS: Readonly<Record<ZoneId, readonly PanelId[]>> = {
  sidebar: SIDEBAR_PANELS,
  bottom: BOTTOM_PANELS,
  right: RIGHT_PANELS,
};

export interface ZoneMeta {
  title: string;
  /** Codicon when the zone is expanded… */
  icon: string;
  /** …and when it is collapsed (VS Code flips the icon, not just its color). */
  iconOff: string;
  hint: string;
}

export const ZONE_META: Readonly<Record<ZoneId, ZoneMeta>> = {
  sidebar: {
    title: m.zone_sidebar(),
    icon: 'layout-sidebar-left',
    iconOff: 'layout-sidebar-left-off',
    hint: 'Ctrl+B',
  },
  bottom: {
    title: m.zone_bottom(),
    icon: 'layout-panel',
    iconOff: 'layout-panel-off',
    hint: 'Ctrl+J',
  },
  right: {
    title: m.zone_right(),
    icon: 'layout-sidebar-right',
    iconOff: 'layout-sidebar-right-off',
    hint: 'Ctrl+Alt+B',
  },
};

export interface PanelMeta {
  title: string;
  /** Codicon name (@vscode/codicons) for the activity bar and the headers. */
  icon: string;
  /** Shortcut displayed in the tooltip, purely informative. */
  hint?: string;
}

export const PANEL_META: Readonly<Record<PanelId, PanelMeta>> = {
  explorer: { title: m.panel_explorer(), icon: 'list-tree', hint: 'Ctrl+Alt+P' },
  files: { title: m.panel_files(), icon: 'files' },
  // No `hint` here: Ctrl+B toggles the sidebar **zone**, not this panel (see ZONE_META).
  // The tooltip advertised it anyway, and the shortcut table revealed the duplicate.
  windows: { title: m.panel_windows(), icon: 'window' },
  history: { title: m.panel_history(), icon: 'history' },
  library: { title: m.panel_library(), icon: 'library' },
  header: { title: m.panel_header(), icon: 'symbol-key' },
  stf: { title: m.panel_stf(), icon: 'graph-line', hint: 'F12' },
  doc: { title: m.panel_doc(), icon: 'book', hint: 'F1' },
  home: { title: m.panel_home(), icon: 'home' },
  desktop: { title: m.panel_desktop(), icon: 'symbol-color' },
  pipeline: { title: m.panel_pipeline(), icon: 'run-all' },
  // `Ctrl+,` is the convention of every editor: honoring it costs one line.
  settings: { title: m.panel_settings(), icon: 'settings-gear', hint: 'Ctrl+,' },
  credits: { title: m.panel_credits(), icon: 'law' },
  selector: { title: m.panel_selector(), icon: 'filter' },
  lightcurve: { title: m.panel_lightcurve(), icon: 'graph-line' },
  rtp: { title: m.panel_rtp(), icon: 'eye' },
  console: { title: m.panel_console(), icon: 'terminal' }, // Ctrl+J toggles the zone, not this panel
  chat: { title: m.panel_chat(), icon: 'comment-discussion' },
};

/** Starting visibility — must stay aligned with DEFAULT_VISIBLE on the Python side. */
export const DEFAULT_VISIBLE: Readonly<Record<PanelId, boolean>> = {
  explorer: true,
  files: false,
  windows: false,
  history: false,
  library: false,
  header: false,
  stf: true,
  doc: false,
  // False: at `true`, reloading the "Processing" perspective would reopen the home tab every
  // time. It opens on a decision (empty session, or a command), not by default.
  home: false,
  desktop: false,
  pipeline: false,
  settings: false,
  credits: false,
  selector: false,
  lightcurve: false,
  rtp: false,
  console: true,
  chat: false,
};

export const BUILTIN_PERSPECTIVES = ['Processing', 'Inspection', 'Script'] as const;
export type BuiltinPerspective = (typeof BUILTIN_PERSPECTIVES)[number];

/**
 * Displayed label of a perspective — the three built-in ones are translated, the others carry
 * the name the user gave them, as is.
 *
 * Going through here rather than displaying the id is what lets `app.layout.load('Processing')`
 * keep working: the name is an identifier on the server side (`layout_backend.py`), and
 * the perspectives already saved on the user's disk carry that very name.
 */
export function perspectiveLabel(name: string): string {
  switch (name) {
    case 'Processing':
      return m.perspective_processing();
    case 'Inspection':
      return m.perspective_inspection();
    case 'Script':
      return m.perspective_script();
    default:
      return name;
  }
}

/**
 * The three presets, rebuilt in code rather than serialized: they must survive a
 * structural change of the shell, which a layout blob would not.
 */
export const PERSPECTIVE_LAYOUTS: Record<BuiltinPerspective, Record<PanelId, boolean>> = {
  Processing: { ...DEFAULT_VISIBLE },
  // Sorting and comparing: the image, its stretch, and the header of what one is looking at.
  Inspection: {
    explorer: false,
    files: false,
    windows: false,
    history: false,
    library: false,
    header: true,
    stf: true,
    doc: false,
    home: false,
    desktop: false,
    pipeline: false,
  settings: false,
  credits: false,
    selector: false,
    lightcurve: false,
    rtp: false,
    console: false,
    chat: false,
  },
  Script: {
    explorer: false,
    // Writing a script means first reaching the server's disk: in Script mode `files` takes
    // the place `windows` occupied. Since the sidebar is **exclusive**, leaving
    // both at `true` would in any case have opened only the first — a dead setting.
    files: true,
    windows: false,
    history: false,
    library: false,
    header: false,
    stf: false,
    doc: true,
    home: false,
    desktop: false,
    pipeline: false,
  settings: false,
  credits: false,
    selector: false,
    lightcurve: false,
    rtp: false,
    console: true,
    chat: false,
  },
};
