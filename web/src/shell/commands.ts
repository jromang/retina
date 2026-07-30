// Command registry — the single source of the shortcuts, the menus and the palette.
//
// Taken from `gui/actions.py::ActionSpec`, including the decisive field: `python`, the equivalent
// line of code. The palette displays it on a second line and Ctrl+C copies it: this is
// learning the API through use, a pillar of the project. A command without a `python` is the
// sign that it does not go through the API — hence an architecture bug, not a cosmetic oversight.

import { m } from '../paraglide/messages';
import { startTour } from './Tour';
import { client } from '../api/client';
import type { ProcessMeta } from '../api/types';
import {
  PANEL_META,
  SIDEBAR_PANELS,
  ZONE_META,
  ZONES,
  perspectiveLabel,
  type PanelId,
} from './panels';
import {
  BUILTIN_PERSPECTIVES,
  layoutLocked,
  openProcesses,
  requestActivate,
  requestPerspective,
  requestToggle,
  requestToggleZone,
} from './layoutClient';
import { toggleAB } from '../viewport/ab';
import { dynamicTool } from '../viewport/dynamicTool';
import { scriptFromBlocks } from '../console/historyScript';
import { blocks } from '../console/transcript';
import { newContainer } from '../pipeline/containerEdit';
import { closeProject, openProject, saveProject, setLanguage } from '../project/project';
import { confirmBox, promptChoice, promptText } from '../ui/prompts';
import { pushToast } from '../notifications/store';
import { activeWindow, processes, windows } from '../state/store';
import { runProcess } from '../processes/jobs';
import { openPalette } from './uiState';
import { SCRIPT_FILTERS, askPath } from './native';
import {
  activeScriptId,
  newScript,
  openScriptFromDisk,
  runFile,
  runInConsole,
  saveScript,
  scriptText,
} from '../scripts/scripts';

export interface Command {
  id: string;
  title: string;
  category: string;
  /** Tabler icon name (`ProcessMeta.icon`) — only processes have one. */
  icon?: string;
  /** Equivalent Python line, displayed by the palette and copyable. */
  python?: string;
  /** Shortcut, in display notation. */
  shortcut?: string;
  /**
   * The shortcut is laid down by a component, not by the global table.
   *
   * The case of the script commands: Monaco binds Ctrl+S and F5 itself in the editor, and
   * consumes them before the event reaches the window. The same chords have a different
   * meaning elsewhere (save the *image*, apply the last process) — that is intended, and it is
   * why these commands must stay outside the table: it requires a unique chord.
   */
  localShortcut?: boolean;
  run: () => void;
}

/** `BUILTIN_PERSPECTIVES` is a literal tuple: `includes` would refuse a string on it. */
function isBuiltin(name: string): boolean {
  return (BUILTIN_PERSPECTIVES as readonly string[]).includes(name);
}

function call(method: string, params?: Record<string, unknown>): void {
  void client.call(method, params).catch((error: unknown) => console.error(method, error));
}

const FILE_COMMANDS: Command[] = [
  {
    id: 'file.open',
    title: m.cmd_file_open(),
    category: m.cat_file(),
    python: 'app.open(chemin)',
    shortcut: 'Ctrl+O',
    run: () => {
      void askPath({ title: m.dialog_open_image() }).then((paths) => {
        if (paths?.[0]) call('app.open', { path: paths[0] });
      });
    },
  },
  {
    id: 'file.save_as',
    title: m.cmd_file_save_as(),
    category: m.cat_file(),
    python: 'app.save(chemin)',
    shortcut: 'Ctrl+S',
    run: () => {
      void askPath({ title: m.dialog_save_as(), save: true }).then((paths) => {
        if (paths?.[0]) call('app.save', { path: paths[0] });
      });
    },
  },
  {
    id: 'file.reload',
    title: m.cmd_file_reload(),
    category: m.cat_file(),
    python: 'app.reload()',
    run: () => void reloadActiveImage().catch((e: unknown) => console.error(e)),
  },
  {
    id: 'file.close_window',
    title: m.cmd_file_close_window(),
    category: m.cat_file(),
    python: 'app.close_window()',
    run: () => call('app.close_window'),
  },
];

/**
 * Reads the active image back from its file — the counterpart of `app.reload()` in the console.
 *
 * Two guards, and no logic beyond that: the domain does all the work (it is the domain that
 * re-reads, replaces and resets the history), the GUI only avoids two surprises.
 * The first is the mute refusal: a window created by a process has no source
 * file, and clicking without seeing anything happen would be incomprehensible. The second is the
 * loss of history — reloading amounts to closing and reopening, so a non-trivial undo
 * stack disappears. We ask nothing when there is nothing to lose: asking a
 * question whose answer is always "yes" teaches people to stop reading it.
 */
async function reloadActiveImage(): Promise<void> {
  const win = activeWindow.value;
  if (!win) return;
  if (!win.file_path) {
    pushToast('warning', m.status_reload_no_file());
    return;
  }
  const main = win.views.find((view) => !view.is_preview);
  const losesHistory = (main?.history.labels.length ?? 1) > 1;
  if (losesHistory && !(await confirmBox(m.prompt_reload_history(), m.prompt_reload()))) return;
  try {
    await client.call('app.reload', { window: win.id });
  } catch (error: unknown) {
    pushToast('error', error instanceof Error ? error.message : String(error));
  }
}

/**
 * Projects — the whole session in one file.
 *
 * Ctrl+S is already taken by `file.save_as` (saving the **image**) and, in the editor, by
 * `script.save`; hence Ctrl+Shift+S here. `buildKeymap` throws on a duplicate chord, so the
 * conflict could not go unnoticed.
 */
const PROJECT_COMMANDS: Command[] = [
  {
    id: 'project.open',
    title: m.cmd_project_open(),
    category: m.cat_project(),
    python: 'app.open_project(chemin)',
    run: () => void openProject().catch((e: unknown) => console.error(e)),
  },
  {
    id: 'project.save',
    title: m.cmd_project_save(),
    category: m.cat_project(),
    python: 'app.save_project(chemin)',
    shortcut: 'Ctrl+Shift+S',
    run: () => void saveProject().catch((e: unknown) => console.error(e)),
  },
  {
    id: 'project.save_as',
    title: m.cmd_project_save_as(),
    category: m.cat_project(),
    python: 'app.save_project(chemin)',
    run: () => void saveProject(true).catch((e: unknown) => console.error(e)),
  },
  {
    id: 'project.close',
    title: m.cmd_project_close(),
    category: m.cat_project(),
    python: 'app.close_project()',
    run: () => void closeProject().catch((e: unknown) => console.error(e)),
  },
  {
    // A deliberate duplicate of `panel.pipeline` (generated for every panel): nobody
    // looks for preprocessing in a "Panels" menu. `show` and not `toggle` — a
    // menu entry must never *close* what it claims to open.
    id: 'pipeline.show',
    title: m.cmd_pipeline_show(),
    category: m.cat_file(),
    icon: 'run-all',
    python: "app.layout.show('pipeline')",
    run: () => call('layout.show', { panel: 'pipeline' }),
  },
];

/**
 * Script mode — the first pillar, owned by the interface.
 *
 * The `python` lines are more than an ornament here: they say exactly which console
 * gesture replaces each command. Opening a script has no dedicated `app.*` and does not want
 * one — an editing tab is chrome, and the domain already knows how to read a file and
 * execute a recipe.
 */
const SCRIPT_COMMANDS: Command[] = [
  {
    id: 'script.new',
    title: m.cmd_script_new(),
    category: m.cat_script(),
    icon: 'file-code',
    python: '# editor: the domain already exposes app.run_recipe(chemin)',
    run: () => {
      newScript();
    },
  },
  {
    id: 'script.open',
    title: m.cmd_script_open(),
    category: m.cat_script(),
    python: 'open(chemin).read()',
    run: () => {
      void askPath({ title: m.dialog_open_script(), filters: SCRIPT_FILTERS }).then((paths) => {
        if (paths?.[0]) {
          void openScriptFromDisk(paths[0]).catch((error: unknown) => console.error(error));
        }
      });
    },
  },
  {
    id: 'script.save',
    title: m.cmd_script_save(),
    category: m.cat_script(),
    python: 'open(chemin, "w").write(source)',
    shortcut: 'Ctrl+S',
    localShortcut: true,
    run: () => {
      const id = activeScriptId.value;
      if (id) void saveScript(id).catch((error: unknown) => console.error(error));
    },
  },
  {
    id: 'script.save_as',
    title: m.cmd_script_save_as(),
    category: m.cat_script(),
    python: 'open(chemin, "w").write(source)',
    run: () => {
      const id = activeScriptId.value;
      if (id) void saveScript(id, true).catch((error: unknown) => console.error(error));
    },
  },
  {
    id: 'container.new',
    title: m.cmd_container_new(),
    category: m.cat_script(),
    icon: 'list-ordered',
    python: 'ProcessContainer()',
    run: () => {
      newContainer();
    },
  },
  {
    id: 'console.to_script',
    title: m.cmd_console_to_script(),
    category: m.cat_script(),
    icon: 'history',
    // The transcript *is* already the Python log of the session (the echo pillar); on the pure
    // console side, the equivalent of the typed entries alone is the `%history` magic.
    python: "%history -f session.py",
    run: () => {
      newScript(scriptFromBlocks(blocks.value, new Date().toLocaleString()));
    },
  },
  {
    id: 'script.run',
    title: m.cmd_script_run(),
    category: m.cat_script(),
    icon: 'play',
    // This line used to announce `app.run_recipe(chemin)` while it sends the **buffer** to the
    // console. The echo is the project's pillar: it cannot lie about what it does. The
    // "run the file" gesture is `script.run_file` below.
    python: '# the editor buffer, sent to the shared console',
    shortcut: 'F5',
    localShortcut: true,
    run: () => {
      const id = activeScriptId.value;
      if (id) runInConsole(scriptText(id));
    },
  },
  {
    id: 'script.run_file',
    title: m.cmd_script_run_file(),
    category: m.cat_script(),
    icon: 'run-all',
    python: 'app.run_recipe(chemin)',
    run: () => {
      const id = activeScriptId.value;
      if (id) void runFile(id).catch((error: unknown) => console.error(error));
    },
  },
];

/**
 * The three `TransparencyMode`s: `[RPC value, Python name, label]` — shared by the
 * palette and the menu. Mirror of the domain's enumeration (`viewport_state.py`).
 *
 * Documented limitation: the command sets the domain (persisted in the project, visible in
 * the snapshot), but the checkerboard/color rendering is waiting on its shader ticket — the
 * WebGL contexts are created `alpha:false` and the shader only samples the nominal channels.
 */
export const TRANSPARENCY_MODES: Array<[string, string, string]> = [
  ['brush', 'BACKGROUND_BRUSH', m.transparency_mode_brush()],
  ['color', 'COLOR', m.transparency_mode_color()],
  ['hide', 'HIDE', m.transparency_mode_hide()],
];

const VIEW_COMMANDS: Command[] = [
  {
    id: 'edit.undo',
    title: m.cmd_edit_undo(),
    category: m.cat_edit(),
    python: 'app.undo()',
    shortcut: 'Ctrl+Z',
    run: () => call('app.undo'),
  },
  {
    id: 'edit.redo',
    title: m.cmd_edit_redo(),
    category: m.cat_edit(),
    python: 'app.redo()',
    shortcut: 'Ctrl+Y',
    run: () => call('app.redo'),
  },
  {
    id: 'view.autostretch',
    title: m.cmd_view_autostretch(),
    category: m.cat_view(),
    python: 'app.compute_auto_stf()',
    run: () => call('app.compute_auto_stf'),
  },
  {
    id: 'view.zoom_in',
    title: m.cmd_view_zoom_in(),
    category: m.cat_view(),
    python: 'app.zoom_in()',
    shortcut: '+',
    run: () => call('app.zoom_in'),
  },
  {
    id: 'view.zoom_out',
    title: m.cmd_view_zoom_out(),
    category: m.cat_view(),
    python: 'app.zoom_out()',
    shortcut: '−',
    run: () => call('app.zoom_out'),
  },
  {
    id: 'view.zoom_11',
    title: m.cmd_view_zoom_11(),
    category: m.cat_view(),
    python: 'app.zoom_1_1()',
    shortcut: '1',
    run: () => call('app.zoom_1_1'),
  },
  {
    id: 'view.zoom_fit',
    title: m.cmd_view_zoom_fit(),
    category: m.cat_view(),
    python: 'app.zoom_to_fit()',
    shortcut: 'F',
    run: () => call('app.zoom_to_fit'),
  },
  // The comparison gestures. Without an entry here, they existed only in the code: the
  // A/B toggle was a key nothing advertised, and linking views an icon without a
  // label. The project's rule is that an expert gesture keeps an explicit path.
  {
    id: 'view.link',
    title: m.cmd_view_link(),
    category: m.cat_view(),
    python: 'app.link_viewports()',
    run: () => call('app.link_viewports'),
  },
  {
    id: 'view.unlink',
    title: m.cmd_view_unlink(),
    category: m.cat_view(),
    python: 'app.unlink_viewports()',
    run: () => call('app.unlink_viewports'),
  },
  {
    id: 'view.compare_ab',
    title: m.cmd_view_compare_ab(),
    category: m.cat_view(),
    // The target depends on the navigation history, which only the shell knows; the Python
    // line shows the domain call the toggle ends up making.
    python: "app.select_view('…')",
    shortcut: 'B',
    run: () => toggleAB(),
  },
  ...TRANSPARENCY_MODES.map(([mode, name, label]) => ({
    id: `view.transparency.${mode}`,
    title: m.view_transparency_mode({ label }),
    category: m.cat_view(),
    // The RPC carries the enumeration's *value* ('brush'), the Python echo its *name*
    // (BACKGROUND_BRUSH) — see app.set_transparency_mode, which echoes mode.name.
    python: `app.set_transparency_mode(retina.TransparencyMode.${name})`,
    run: () => call('app.set_transparency_mode', { mode }),
  })),
];

/**
 * The ten `MaskDisplayMode`s with their label — shared by the palette, the menu and the status
 * bar, so that the three name the same thing. Mirror of the domain's enumeration
 * (python/retina/model/viewport_state.py); `web/tests/mask.test.ts` checks the coverage.
 */
export const MASK_DISPLAY_MODES: Array<[string, string]> = [
  ['overlay_red', m.mask_mode_overlay_red()],
  ['overlay_green', m.mask_mode_overlay_green()],
  ['overlay_blue', m.mask_mode_overlay_blue()],
  ['overlay_yellow', m.mask_mode_overlay_yellow()],
  ['overlay_magenta', m.mask_mode_overlay_magenta()],
  ['overlay_cyan', m.mask_mode_overlay_cyan()],
  ['overlay_orange', m.mask_mode_overlay_orange()],
  ['overlay_violet', m.mask_mode_overlay_violet()],
  ['replace', m.mask_mode_replace()],
  ['multiply', m.mask_mode_multiply()],
];

/**
 * Masks — the domain chain existed in full, without a single path in the interface.
 *
 * The toggles read the current state rather than taking an argument: a palette
 * command has no argument, and "Show the mask" / "Hide the mask" as two distinct
 * entries would make one entry out of two dead at any moment.
 */
const MASK_COMMANDS: Command[] = [
  {
    id: 'mask.pick',
    title: m.cmd_mask_pick(),
    category: m.cat_mask(),
    python: "app.set_mask('id_de_vue')",
    run: () => {
      const target = activeWindow.value;
      if (!target) return;
      // Filtered on geometry: the domain accepts any view when the mask is laid
      // down and only throws at the first process (`mask_array`). Offering a mask that
      // will fail later would be offering a trap rather than a choice.
      const candidates = windows.value
        .flatMap((w) => w.views)
        .filter((v) => v.width === target.width && v.height === target.height)
        .map((v) => ({ value: v.id, label: `${v.id} (${v.width}×${v.height})` }));
      void promptChoice(
        candidates.length > 0
          ? m.prompt_mask_source({ view: target.id })
          : m.prompt_mask_none({ width: target.width, height: target.height }),
        candidates,
        m.prompt_apply(),
      ).then((id) => {
        if (id) call('app.set_mask', { source: id, window: target.id });
      });
    },
  },
  {
    id: 'mask.remove',
    title: m.cmd_mask_remove(),
    category: m.cat_mask(),
    python: 'app.remove_mask()',
    run: () => call('app.remove_mask'),
  },
  {
    id: 'mask.toggle_visible',
    title: m.cmd_mask_toggle_visible(),
    category: m.cat_mask(),
    python: 'app.set_mask_visible(True)',
    shortcut: 'Ctrl+K',
    run: () => {
      const win = activeWindow.value;
      if (win) call('app.set_mask_visible', { visible: !win.viewport.mask_visible });
    },
  },
  {
    id: 'mask.toggle_enabled',
    title: m.cmd_mask_toggle_enabled(),
    category: m.cat_mask(),
    python: 'app.set_mask_enabled(True)',
    run: () => {
      const win = activeWindow.value;
      if (win?.mask) call('app.set_mask_enabled', { enabled: !win.mask.enabled });
    },
  },
  {
    id: 'mask.toggle_inverted',
    title: m.cmd_mask_toggle_inverted(),
    category: m.cat_mask(),
    python: 'app.set_mask_inverted(True)',
    run: () => {
      const win = activeWindow.value;
      if (win?.mask) call('app.set_mask_inverted', { inverted: !win.mask.inverted });
    },
  },
  ...MASK_DISPLAY_MODES.map(([mode, label]) => ({
    id: `mask.display.${mode}`,
    title: m.mask_render_mode({ label }),
    category: m.cat_mask(),
    python: `app.set_mask_display_mode(retina.MaskDisplayMode.${mode.toUpperCase()})`,
    run: () => call('app.set_mask_display_mode', { mode }),
  })),
];

/**
 * Exiting a dynamic tool.
 *
 * Without it, leaving a crop or a stamp meant finding the checkbox of the panel that
 * had armed it again. The command does nothing if no tool is armed: Esc serves to close
 * plenty of other things, and it must not write a `set_interaction_mode` echo every time.
 *
 * The shortcut does not fire when the focus is in an input (`isTyping`): the palette and the
 * modals therefore keep their own Esc.
 */
const TOOL_COMMANDS: Command[] = [
  {
    id: 'view.exit_tool',
    title: m.cmd_view_exit_tool(),
    category: m.cat_view(),
    python: 'app.set_interaction_mode(retina.InteractionMode.READOUT)',
    shortcut: 'Esc',
    run: () => {
      if (!dynamicTool.value) return;
      call('app.set_interaction_mode', { mode: 'readout' });
    },
  },
];

/**
 * Readout — the value probe, and its magnifier.
 *
 * `ReadoutOptions` was served and serialized without any interface path leading to it: the
 * magnifier always showed and the precision was frozen at five decimals in the code.
 */
const READOUT_COMMANDS: Command[] = [
  {
    id: 'readout.toggle_loupe',
    title: m.cmd_readout_toggle_loupe(),
    category: m.cat_view(),
    python: 'app.set_readout_options(show_loupe=True)',
    run: () => {
      const win = activeWindow.value;
      if (win) call('app.set_readout_options', { show_loupe: !win.viewport.readout.show_loupe });
    },
  },
  ...[1, 3, 5, 9].map((size) => ({
    id: `readout.probe_${size}`,
    title: m.cmd_readout_probe({ size }),
    category: m.cat_view(),
    python: `app.set_readout_options(probe_size=${size})`,
    run: () => call('app.set_readout_options', { probe_size: size }),
  })),
];

/** Inspection & comparison — screens that would otherwise be unreachable outside the palette. */
const INSPECTION_COMMANDS: Command[] = [
  {
    id: 'selector.show',
    title: m.cmd_selector_show(),
    category: m.cat_inspection(),
    python: "app.layout.show('selector')",
    run: () => call('layout.show', { panel: 'selector' }),
  },
  {
    id: 'blink.show',
    title: m.cmd_blink_show(),
    category: m.cat_inspection(),
    python: "app.layout.open_process('Blink')",
    run: () => call('layout.open_process', { process_id: 'Blink' }),
  },
  {
    id: 'header.show',
    title: m.cmd_header_show(),
    category: m.cat_inspection(),
    python: "app.layout.activate('header')",
    run: () => requestActivate('header'),
  },
];

/**
 * Commands of the shell itself — with no domain action behind them.
 *
 * Until now they lived hard-coded in the workbench's keyboard handler. Lifting them up to the
 * registry is what lets the shortcut table be *derived*: as long as a key
 * had no command, it had to be recoded by hand, and the two implementations
 * diverged (the handler's Ctrl+Z called `app.undo` as a duplicate of `edit.undo`).
 */
const SHELL_COMMANDS: Command[] = [
  {
    id: 'help.tour',
    title: m.cmd_help_tour(),
    category: m.cat_help(),
    // No `python:` — the tour is chrome, like the palette: it does nothing to the
    // domain, it shows where things are. What the user does set in it, on the other hand
    // ("stop showing this"), goes through `app.preferences`, which echoes.
    run: () => startTour(),
  },
  {
    id: 'palette.open',
    title: m.cmd_palette_open(),
    category: m.cat_help(),
    // The palette is chrome: it executes nothing by itself. It is the exception the
    // menu model already names `kind: 'action'`.
    shortcut: 'Ctrl+Shift+P',
    run: () => openPalette(),
  },
  {
    id: 'process.apply_last',
    title: m.cmd_process_apply_last(),
    category: m.cat_process(),
    // Muscle memory carried over from the reference application. In a script editor, Monaco has
    // already consumed F5 to run the script — that is intended, and it is why `script.run` is
    // `localShortcut`.
    python: 'X().execute_on(app.active_view)',
    shortcut: 'F5',
    run: () => {
      const last = openProcesses.value.at(-1);
      const meta = last ? processes.value.find((p) => p.process_id === last) : undefined;
      if (!meta) return;
      const params = Object.fromEntries(meta.parameters.map((p) => [p.id, p.default]));
      runProcess(meta.process_id, params).catch((error: unknown) => console.error(error));
    },
  },
];

/**
 * Interface language — three commands, one per choice.
 *
 * They go through `project.set_language`, hence through `app.set_language`, hence the Python echo
 * leaves as for any other gesture: the parity pillar holds for a preference too.
 * Three entries rather than a toggle, because "automatic" is a third state — and
 * one must be able to come back to it without guessing.
 *
 * The reload that follows is not triggered here: it is `session.changed` that brings it, which
 * means the same reload happens when the language is changed from the console.
 */
const LANGUAGE_COMMANDS: Command[] = [
  {
    id: 'language.auto',
    title: m.cmd_language_auto(),
    category: m.cat_help(),
    python: 'app.set_language(None)',
    run: () => setLanguage(null),
  },
  {
    id: 'language.en',
    title: m.cmd_language_en(),
    category: m.cat_help(),
    python: "app.set_language('en')",
    run: () => setLanguage('en'),
  },
  {
    id: 'language.fr',
    title: m.cmd_language_fr(),
    category: m.cat_help(),
    python: "app.set_language('fr')",
    run: () => setLanguage('fr'),
  },
];

/** Collapse/expand the three zones — the same actions as the title bar icons. */
const ZONE_COMMANDS: Command[] = ZONES.map((zone) => ({
  id: `zone.${zone}`,
  title: m.cmd_zone_toggle({ zone: ZONE_META[zone].title }),
  category: m.cat_layout(),
  python: `app.layout.toggle_zone('${zone}')`,
  shortcut: ZONE_META[zone].hint,
  run: () => requestToggleZone(zone),
}));

const LAYOUT_COMMANDS: Command[] = [
  ...(['Processing', 'Inspection', 'Script'] as const).map((name, index) => ({
    id: `layout.perspective_${index + 1}`,
    title: m.cmd_layout_load({ name: perspectiveLabel(name) }),
    category: m.cat_layout(),
    python: `app.layout.load(${JSON.stringify(name)})`,
    shortcut: `Ctrl+Alt+${index + 1}`,
    run: () => requestPerspective(name),
  })),
  {
    id: 'layout.save',
    title: m.cmd_layout_save(),
    category: m.cat_layout(),
    python: "app.layout.save('Ma disposition')",
    run: () => {
      void promptText(m.prompt_layout_name(), '', m.prompt_save()).then((name) => {
        // The server does not know the layout: it will ask us for it through
        // `layout.command {op: request_save}`, which layoutClient answers.
        if (name) call('layout.save', { name });
      });
    },
  },
  {
    id: 'layout.delete',
    title: m.cmd_layout_delete(),
    category: m.cat_layout(),
    python: "app.layout.delete('Ma disposition')",
    run: () => {
      void client
        .call<string[]>('layout.perspectives')
        .then(async (names) => {
          const custom = names.filter((name) => !isBuiltin(name));
          if (custom.length === 0) {
            await confirmBox(m.prompt_no_saved_layout(), m.prompt_close());
            return;
          }
          const chosen = await promptText(
            m.prompt_delete_which({ names: custom.join(' · ') }),
            custom[0] ?? '',
            m.prompt_delete(),
          );
          if (chosen && custom.includes(chosen)) call('layout.delete', { name: chosen });
        })
        .catch((error: unknown) => console.error(error));
    },
  },
  {
    id: 'layout.reset',
    title: m.cmd_layout_reset(),
    category: m.cat_layout(),
    python: 'app.layout.reset()',
    run: () => call('layout.reset'),
  },
  {
    id: 'layout.toggle_lock',
    title: m.cmd_layout_toggle_lock(),
    category: m.cat_layout(),
    // The state feedback arrives through `layout.command {op: set_locked}` → `layoutLocked`,
    // already wired: the web obeyed the lock without being able to set it.
    python: 'app.layout.lock(not app.layout.locked)',
    run: () => call('layout.lock', { locked: !layoutLocked.value }),
  },
];

/** Saved layouts become commands, like the presets. */
function perspectiveCommands(names: readonly string[]): Command[] {
  return names
    .filter((name) => !isBuiltin(name))
    .map((name) => ({
      id: `layout.perspective.${name}`,
      title: m.cmd_layout_load({ name: perspectiveLabel(name) }),
      category: m.cat_layout(),
      python: `app.layout.load(${JSON.stringify(name)})`,
      run: () => requestPerspective(name),
    }));
}

/** One command per panel — the palette becomes the universal path to the UI. */
function panelCommands(): Command[] {
  return (Object.keys(PANEL_META) as PanelId[]).map((panel) => {
    const meta = PANEL_META[panel];
    const exclusive = SIDEBAR_PANELS.includes(panel);
    const base: Command = {
      id: `panel.${panel}`,
      title: m.cmd_panel_show({ panel: meta.title }),
      category: m.cat_panels(),
      python: `app.layout.${exclusive ? 'activate' : 'toggle'}('${panel}')`,
      run: () => (exclusive ? requestActivate(panel) : requestToggle(panel)),
    };
    return meta.hint ? { ...base, shortcut: meta.hint } : base;
  });
}

/** What the "recent" menus need to know. */
export interface RecentPaths {
  files: readonly string[];
  projects: readonly string[];
}

export const EMPTY_RECENT: RecentPaths = { files: [], projects: [] };

function shortName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

/**
 * One command per recent path — on the model of `perspectiveCommands`.
 *
 * They go through the registry rather than being inert menu entries: the palette
 * finds them for free, and each carries its `python` line, like every command.
 */
export function recentCommands(recent: RecentPaths = EMPTY_RECENT): Command[] {
  return [
    ...recent.files.map((path) => ({
      id: `recent.file.${path}`,
      title: shortName(path),
      category: m.cat_recent_files(),
      python: `app.open(${JSON.stringify(path)})`,
      run: () => call('app.open', { path }),
    })),
    ...recent.projects.map((path) => ({
      id: `recent.project.${path}`,
      title: shortName(path),
      category: m.cat_recent_projects(),
      python: `app.open_project(${JSON.stringify(path)})`,
      run: () => void openProject(path).catch((e: unknown) => console.error(e)),
    })),
  ];
}

export function baseCommands(
  perspectives: readonly string[] = [],
  recent: RecentPaths = EMPTY_RECENT,
): Command[] {
  return [
    ...FILE_COMMANDS,
    ...PROJECT_COMMANDS,
    ...recentCommands(recent),
    ...SCRIPT_COMMANDS,
    ...VIEW_COMMANDS,
    ...SHELL_COMMANDS,
    ...LANGUAGE_COMMANDS,
    ...MASK_COMMANDS,
    ...TOOL_COMMANDS,
    ...READOUT_COMMANDS,
    ...INSPECTION_COMMANDS,
    ...ZONE_COMMANDS,
    ...LAYOUT_COMMANDS,
    ...perspectiveCommands(perspectives),
    ...panelCommands(),
  ];
}

/**
 * The 115 processes, as commands — for the palette *and* for the Process menu.
 *
 * Takes the list as an argument rather than reading the signal: it is a pure factory, hence
 * testable without bringing the store up.
 */
export function processCommands(list: readonly ProcessMeta[]): Command[] {
  return list.map((process) => ({
    id: `process.${process.process_id}`,
    title: process.process_id,
    category: process.category,
    icon: process.icon,
    python: `${process.process_id}().execute_on(app.active_view)`,
    run: () => call('layout.open_process', { process_id: process.process_id }),
  }));
}

/**
 * The complete registry, indexed by id — what the menu model resolves against.
 *
 * The menus reference commands by id rather than redefining them: one single
 * implementation, one single Python echo, and a mistyped id shows up in a test rather than on click.
 */
export function commandIndex(
  perspectives: readonly string[] = [],
  list: readonly ProcessMeta[] = [],
  recent: RecentPaths = EMPTY_RECENT,
): Map<string, Command> {
  return new Map(
    [...baseCommands(perspectives, recent), ...processCommands(list)].map((c) => [c.id, c]),
  );
}

/** Insensitive to accents and to case — an accented title must still come up on "decon". */
export function fold(text: string): string {
  return text
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase();
}

/**
 * Subsequence score, ported from `gui/palette.py::fuzzy_score`.
 * `null` = the query is not a subsequence, hence not a result.
 */
export function fuzzyScore(haystack: string, needle: string): number | null {
  if (!needle) return 0;
  const hay = fold(haystack);
  const query = fold(needle);
  let score = 0;
  let last = -2;
  let index = 0;
  for (const char of query) {
    const found = hay.indexOf(char, index);
    if (found < 0) return null;
    if (found === last + 1) score += 3; // consecutive characters
    else if (found === 0 || ' .-_/:'.includes(hay[found - 1] ?? '')) score += 2; // start of a word
    else score += 1;
    last = found;
    index = found + 1;
  }
  return score;
}
