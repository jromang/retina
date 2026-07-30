// Guided tour of the first launch.
//
// A hand-written component rather than a library: the need amounts to a dimmed backdrop, a
// positioned card and two buttons, and the repository avoids dependencies that do not pay
// their way. No abstraction layer — the steps are data (`tourSteps.ts`),
// this file only displays them.
//
// Two things this component deliberately does NOT do:
//
//   - it never clicks on anyone's behalf. It opens the panel the step talks about (through the
//     same `requestActivate` as the ActivityBar) and points at it; it simulates no gesture.
//     A tour that drives the application teaches you to watch it, not to use it.
//   - it blocks nothing. The backdrop does not intercept clicks on the application: one can
//     interrupt, try things out, and the tour waits. A modal would have turned
//     discovery into a formality to be dispatched.
//
// The `session.show_tour` preference is unchecked at the end **and** on the first "Skip":
// in both cases the user has answered the question, and asking it again on the next
// launch would be asking once too often. It is a setting visible in the preferences
// panel, not a hidden flag — and the `help.tour` command replays it on demand.

import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { signal } from '@preact/signals';

import { client } from '../api/client';
import { m } from '../paraglide/messages';
import { requestActivate } from './layoutClient';
import { TOUR_STEPS, visibleSteps, type TourStep } from './tourSteps';

/** Tour in progress: `null` = no tour. Driven by the command and by startup. */
export const tourRunning = signal<boolean>(false);

/** Margin between the card and the element being pointed at, in pixels. */
const GAP = 12;
/** Width of the card — enough for three lines of text, no more. */
const CARD_WIDTH = 320;

export function startTour(): void {
  tourRunning.value = true;
}

let startupDecided = false;

/**
 * Starts the tour at launch if the user has not already dismissed it.
 *
 * Called once, after the first snapshot: the tour points at panels, and they
 * must be mounted. The decision is taken **on the server side** (the preference), not
 * in a `localStorage` — otherwise the tour would come back on every browser, and the
 * setting would not be in the preferences panel with the others.
 */
export function startTourIfFirstRun(): void {
  if (startupDecided) return;
  startupDecided = true;
  // `preferences.get` returns the raw value, not an object — the same contract as in the console.
  void client
    .call<boolean>('preferences.get', { key: 'session.show_tour' })
    .then((show) => {
      if (show) startTour();
    })
    .catch(() => undefined);
}

interface Placement {
  left: number;
  top: number;
  highlight: DOMRect | null;
}

/** Places the card against the anchor, keeping it inside the window. */
function place(anchor: Element | null): Placement {
  const vw = globalThis.innerWidth;
  const vh = globalThis.innerHeight;
  if (!anchor) {
    return { left: (vw - CARD_WIDTH) / 2, top: vh / 3, highlight: null };
  }
  const rect = anchor.getBoundingClientRect();
  // To the right if it fits, otherwise to the left, otherwise below: the order follows the layout
  // (activity bar and side panels are on the left, the center is wide).
  let left = rect.right + GAP;
  if (left + CARD_WIDTH > vw - GAP) left = rect.left - CARD_WIDTH - GAP;
  if (left < GAP) left = Math.min(Math.max(GAP, rect.left), vw - CARD_WIDTH - GAP);
  const top = Math.min(Math.max(GAP, rect.top), vh - 200);
  return { left, top, highlight: rect };
}

export function Tour() {
  const [index, setIndex] = useState(0);
  const [steps, setSteps] = useState<TourStep[]>([]);
  const [placement, setPlacement] = useState<Placement>({
    left: 0,
    top: 0,
    highlight: null,
  });
  const card = useRef<HTMLDivElement>(null);

  // The steps are filtered at startup, once: a layout may hide a
  // panel, and a step that pointed into the void is worth less than no step at all.
  useEffect(() => {
    if (!tourRunning.value) return;
    setSteps(visibleSteps(TOUR_STEPS));
    setIndex(0);
  }, [tourRunning.value]);

  const step = steps[index];

  // Open the panel **before** measuring: otherwise the card would be placed against an element
  // that is not there yet, and the first render would point beside it.
  useEffect(() => {
    if (step?.panel) requestActivate(step.panel);
  }, [step?.id]);

  useLayoutEffect(() => {
    if (!step) return;
    const measure = () => {
      setPlacement(place(step.anchor ? document.querySelector(step.anchor) : null));
    };
    // One frame of waiting: opening a panel and the width transition of the zones
    // are not finished by the time the effect runs.
    const timer = globalThis.setTimeout(measure, 60);
    measure();
    globalThis.addEventListener('resize', measure);
    return () => {
      globalThis.clearTimeout(timer);
      globalThis.removeEventListener('resize', measure);
    };
  }, [step?.id, step?.anchor]);

  useEffect(() => {
    if (tourRunning.value) card.current?.focus();
  }, [index, tourRunning.value]);

  if (!tourRunning.value || !step) return null;

  const finish = () => {
    tourRunning.value = false;
    // Through `preferences.set`, like the settings panel: the gesture echoes in Python and
    // reads back in the console. The tour has no power of its own.
    void client
      .call('preferences.set', { key: 'session.show_tour', value: false })
      .catch(() => undefined);
  };

  const next = () => {
    if (index + 1 >= steps.length) finish();
    else setIndex(index + 1);
  };

  const { left, top, highlight } = placement;
  const last = index + 1 >= steps.length;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 60,
        // The backdrop does not capture clicks: the tour accompanies, it does not trap.
        pointerEvents: 'none',
      }}
    >
      {highlight && (
        <div
          aria-hidden="true"
          style={{
            position: 'fixed',
            left: `${highlight.left}px`,
            top: `${highlight.top}px`,
            width: `${highlight.width}px`,
            height: `${highlight.height}px`,
            border: '2px solid var(--vscode-focusBorder)',
            borderRadius: '4px',
            // The drop shadow dims everything EXCEPT the element being pointed at, without having
            // to cut out a mask: it is the simplest technique that gives a real spotlight.
            boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.45)',
            transition: 'all 120ms ease-out',
          }}
        />
      )}
      <div
        ref={card}
        role="dialog"
        aria-label={m.tour_label()}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === 'Escape') finish();
          if (event.key === 'Enter') next();
        }}
        style={{
          position: 'fixed',
          left: `${left}px`,
          top: `${top}px`,
          width: `${CARD_WIDTH}px`,
          pointerEvents: 'auto',
          background: 'var(--vscode-editorWidget-background)',
          border: '1px solid var(--vscode-widget-border, var(--vscode-panel-border))',
          borderRadius: '6px',
          boxShadow: '0 6px 24px rgba(0, 0, 0, 0.4)',
          padding: '14px 16px',
          font: 'var(--retina-font-ui)',
          fontSize: '13px',
        }}
      >
        <h2 style={{ margin: '0 0 6px', fontSize: '14px' }}>{step.title()}</h2>
        <p style={{ margin: '0 0 12px', lineHeight: 1.5, color: 'var(--vscode-foreground)' }}>
          {step.body()}
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '11px', color: 'var(--vscode-descriptionForeground)' }}>
            {m.tour_progress({ current: index + 1, total: steps.length })}
          </span>
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={finish}>
            {last ? m.tour_close() : m.tour_skip()}
          </button>
          {!last && (
            <button className="btn" onClick={next}>
              {m.tour_next()}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
