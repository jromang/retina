// Bridges to the native shell — file dialogs.
//
// # Why not `<input type="file">`
//
// The files live on the **server** side: `app.open(path)` reads a FITS from the disk of
// the machine running Python. The HTML picker only yields uploaded content and
// deliberately hides the path — unusable here. The native shell, on the other hand, returns a path.
//
// In browser mode (without a shell), these functions return `null`: the caller falls back on
// manual entry. Browser mode remains a deliberately degraded mode.

import { type FileFilter, readFilters } from '../api/formats';
import { m } from '../paraglide/messages';
import { promptText } from '../ui/prompts';

export type { FileFilter };

interface RetinaShell {
  invoke(cmd: string, args?: Record<string, unknown>): Promise<unknown>;
}

declare global {
  interface Window {
    __RETINA_SHELL__?: boolean;
    retinaShell?: RetinaShell;
  }
}

/** True if the application is running in its native window (and not in a browser). */
export function inNativeShell(): boolean {
  return window.__RETINA_SHELL__ === true && typeof window.retinaShell?.invoke === 'function';
}

/** Scripts and recipes — what `app.run_recipe` can execute. */
export const SCRIPT_FILTERS: FileFilter[] = [
  { name: m.filter_python_scripts(), extensions: ['py'] },
];

/** Recipes serialized to XML, exchangeable between installations. */
export const RECIPE_FILTERS: FileFilter[] = [
  { name: m.filter_recipes(), extensions: ['xml'] },
];

/** Projects — a complete session in a single file. */
export const PROJECT_FILTERS: FileFilter[] = [
  { name: m.filter_projects(), extensions: ['retina'] },
];

async function invoke<T>(cmd: string, args: Record<string, unknown>): Promise<T | null> {
  if (!inNativeShell()) return null;
  try {
    return (await window.retinaShell!.invoke(cmd, args)) as T;
  } catch (error) {
    console.error('native dialog', error);
    return null;
  }
}

export function openFileDialog(
  title: string = m.dialog_open_image(),
  filters: FileFilter[] = readFilters(),
  directory?: string,
): Promise<string | null> {
  return invoke<string>('open_file', { title, filters, directory });
}

export function openFilesDialog(
  title: string = m.dialog_choose_files(),
  filters: FileFilter[] = readFilters(),
): Promise<string[] | null> {
  return invoke<string[]>('open_files', { title, filters });
}

export function openFolderDialog(
  title: string = m.dialog_choose_folder(),
): Promise<string | null> {
  return invoke<string>('open_folder', { title });
}

export function saveFileDialog(
  title: string = m.dialog_save_as(),
  filename = '',
  filters: FileFilter[] = readFilters(),
  directory?: string,
): Promise<string | null> {
  return invoke<string>('save_file', { title, filename, filters, directory });
}

/**
 * Asks for a path — native dialog if the shell is there, manual entry otherwise.
 *
 * Centralized here so that the fallback does not have to be rewritten in every field.
 */
export async function askPath(options: {
  title: string;
  filters?: FileFilter[];
  multiple?: boolean;
  save?: boolean;
  folder?: boolean;
  filename?: string;
  /**
   * Folder the dialog opens in. The Rust shell has always accepted it and nobody
   * was sending it: reopening a project in its own folder saves three clicks.
   */
  directory?: string;
}): Promise<string[] | null> {
  if (inNativeShell()) {
    if (options.folder) {
      const path = await openFolderDialog(options.title);
      return path ? [path] : null;
    }
    if (options.save) {
      const path = await saveFileDialog(
        options.title, options.filename ?? '', options.filters, options.directory);
      return path ? [path] : null;
    }
    if (options.multiple) return await openFilesDialog(options.title, options.filters);
    const path = await openFileDialog(options.title, options.filters, options.directory);
    return path ? [path] : null;
  }
  // Browser mode: the HTML picker does not return a path (see header), so we ask for
  // manual entry. `promptText` and not `globalThis.prompt` — the latter blocks the event loop
  // and is not guaranteed in an embedded WebView.
  const typed = await promptText(m.prompt_path({ title: options.title }), options.filename ?? '');
  return typed ? [typed] : null;
}
