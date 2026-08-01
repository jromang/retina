// Steps of the guided tour — the data, separated from its display.
//
// Astro processing software is not easily learned by exploring: nothing says where
// things are, and the vocabulary assumes it is already known. The tour does not
// claim to teach astrophotography; it shows **where** the five places
// one uses every day are, and above all what sets us apart — the console that writes
// the Python of each gesture by itself.
//
// `anchor` is a CSS selector. A step whose anchor is absent from the DOM is **skipped**
// rather than rendered in the center of an empty screen: the layout is configurable (collapsed
// zones, perspectives), and promising to show a panel that is not there would be worse
// than saying nothing. `panel` asks the shell to open what is needed before pointing at it.
//
// Those two rules used to fight each other. The filter runs **once, at start**, before any
// step has opened its `panel` — so with the bottom zone collapsed, the console step, the one
// that presents what sets the product apart, vanished in silence and the counter read "5 of
// 5". A step that declares a `panel` is therefore never filtered: it brings its own anchor
// into existence.

import { m } from '../paraglide/messages';
import type { PanelId } from './panels';

export interface TourStep {
  /** Stable identifier — used as a render key and as a landmark in the tests. */
  id: string;
  /** Selector of the element to point at; `null` = centered card (welcome and conclusion). */
  anchor: string | null;
  /** Panel to open before this step, if it is not already. */
  panel?: PanelId;
  title: () => string;
  body: () => string;
}

export const TOUR_STEPS: readonly TourStep[] = [
  {
    id: 'welcome',
    anchor: null,
    title: () => m.tour_welcome_title(),
    body: () => m.tour_welcome_body(),
  },
  {
    id: 'viewport',
    anchor: '.center',
    title: () => m.tour_viewport_title(),
    body: () => m.tour_viewport_body(),
  },
  {
    id: 'processes',
    anchor: '[data-activity="explorer"]',
    panel: 'explorer',
    title: () => m.tour_processes_title(),
    body: () => m.tour_processes_body(),
  },
  {
    id: 'console',
    anchor: '.bottom',
    panel: 'console',
    title: () => m.tour_console_title(),
    body: () => m.tour_console_body(),
  },
  {
    id: 'pipeline',
    anchor: '[data-activity="pipeline"]',
    title: () => m.tour_pipeline_title(),
    body: () => m.tour_pipeline_body(),
  },
  {
    id: 'help',
    anchor: null,
    title: () => m.tour_help_title(),
    body: () => m.tour_help_body(),
  },
];

/**
 * The steps that can actually be shown: those with no anchor, those that open their own
 * panel, and those whose anchor is already in the DOM.
 */
export function visibleSteps(
  steps: readonly TourStep[] = TOUR_STEPS,
  exists: (selector: string) => boolean = (s) => document.querySelector(s) !== null,
): TourStep[] {
  return steps.filter(
    (step) => step.anchor === null || step.panel !== undefined || exists(step.anchor),
  );
}
