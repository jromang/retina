// The guided tour has to keep the promise it makes: every step points at somewhere that
// exists. Since the layout is configurable (collapsed zones, perspectives, closed panels), a
// step whose anchor is missing must be **skipped** — shining a spotlight on nothing would be
// worse than saying nothing at all.

import { describe, expect, it } from 'vitest';

import { TOUR_STEPS, visibleSteps } from '../src/shell/tourSteps';

describe('tour steps', () => {
  it('returns a translated title and body for each of them', () => {
    for (const step of TOUR_STEPS) {
      expect(step.title(), `empty title: ${step.id}`).toBeTruthy();
      expect(step.body(), `empty body: ${step.id}`).toBeTruthy();
    }
  });

  it('has unique identifiers — they are used as render keys', () => {
    const ids = TOUR_STEPS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('starts and ends with a centred card that points at nothing', () => {
    expect(TOUR_STEPS[0]?.anchor).toBeNull();
    expect(TOUR_STEPS.at(-1)?.anchor).toBeNull();
  });

  it('skips a step whose anchor is absent from the DOM', () => {
    const visible = visibleSteps(TOUR_STEPS, () => false);

    expect(visible.every((s) => s.anchor === null)).toBe(true);
    expect(visible.length).toBeGreaterThan(0);
  });

  it('keeps everything when the layout is complete', () => {
    expect(visibleSteps(TOUR_STEPS, () => true)).toHaveLength(TOUR_STEPS.length);
  });

  it('requests the panel be opened for the steps that point at one', () => {
    // Without that, the step would point at a collapsed panel: the spotlight would land on an
    // empty area, and the text would talk about something invisible.
    const console = TOUR_STEPS.find((s) => s.id === 'console');
    expect(console?.panel).toBe('console');
  });
});
