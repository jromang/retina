// Saving an image — the one place that decides between the linear data and what the screen
// shows.
//
// # Why this is not just a call to `app.save`
//
// A linear astronomical image has its sky background around 1e-3. Written into a format that
// quantizes to 8 bits, every one of those values lands on the same black, and the exported
// picture looks empty — while the viewport, which applies the screen transfer function, shows a
// perfectly visible nebula. That gap is invisible from the file dialog, and a user meeting it
// concludes the export is broken rather than that they exported the wrong thing.
//
// So: when the target quantizes **and** a non-identity STF is being displayed, the choice is put
// to the user. FITS, XISF and float TIFF never ask — they carry the linear data faithfully, and
// stretching into them would be the destructive answer.

import { client } from '../api/client';
import { isByteFormat, writeFilters } from '../api/formats';
import type { ViewState } from '../api/types';
import { m } from '../paraglide/messages';
import { stfIsVisible } from '../state/store';
import { promptChoice } from '../ui/prompts';
import { askPath } from './native';

/**
 * Asks for a path, then saves. Returns the path written, or `null` if the user backed out —
 * at the file dialog or at the stretch question, which is a real way out and not a default.
 */
export async function saveImageAs(
  view: ViewState | null | undefined,
  windowId?: string,
  title: string = m.dialog_save_as(),
): Promise<string | null> {
  const chosen = await askPath({ title, save: true, filters: writeFilters() });
  const path = chosen?.[0];
  if (!path) return null;

  let stretch = false;
  if (isByteFormat(path) && stfIsVisible(view)) {
    const answer = await promptChoice(m.dialog_export_stretch(), [
      { value: 'stretch', label: m.dialog_export_stretch_apply() },
      { value: 'linear', label: m.dialog_export_stretch_linear() },
    ]);
    if (answer === null) return null;
    stretch = answer === 'stretch';
  }

  const args: Record<string, unknown> = { path, stretch };
  if (windowId) args['window'] = windowId;
  await client.call('app.save', args);
  return path;
}
