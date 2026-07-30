// Editing a recipe: reorder, insert, remove.
//
// Order is the whole meaning of a ProcessContainer — stretch then denoise is not denoise then
// stretch. These three operations are therefore the part of the panel that deserves a test, well
// ahead of its rendering.

import { describe, expect, it, vi } from 'vitest';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const {
  adoptContainer,
  closeContainer,
  containerById,
  insertStep,
  markContainerSaved,
  moveStep,
  newContainer,
  isEnabled,
  removeStep,
  setStepEnabled,
  setStepMask,
  setSteps,
} = await import('../src/pipeline/containerEdit');

type Step = { process_id: string; values: Record<string, unknown>; enabled?: boolean; mask?: string; mask_inverted?: boolean };
const step = (id: string): Step => ({ process_id: id, values: {} });
const ids = (steps: readonly Step[]) => steps.map((s) => s.process_id);

const ABC = [step('A'), step('B'), step('C')];

describe('reordering', () => {
  it('moves a step down one slot', () => {
    // `to` is the **final** position, not the index to insert in front of: the two conventions
    // differ by exactly one position in this case, and confusing them yields a move that looks
    // like it did nothing.
    expect(ids(moveStep(ABC, 0, 1))).toEqual(['B', 'A', 'C']);
  });

  it('moves a step up, and all the way to either end', () => {
    expect(ids(moveStep(ABC, 2, 0))).toEqual(['C', 'A', 'B']);
    expect(ids(moveStep(ABC, 0, 2))).toEqual(['B', 'C', 'A']);
  });

  it('leaves the list untouched on a no-op or out-of-range move', () => {
    expect(ids(moveStep(ABC, 1, 1))).toEqual(['A', 'B', 'C']);
    expect(ids(moveStep(ABC, 9, 0))).toEqual(['A', 'B', 'C']);
    expect(ids(moveStep(ABC, -1, 0))).toEqual(['A', 'B', 'C']);
  });

  it('never mutates the list it was given', () => {
    const source = [...ABC];
    moveStep(source, 0, 2);
    expect(ids(source)).toEqual(['A', 'B', 'C']);
  });
});

describe('insertion and removal', () => {
  it('inserts at the requested rank, and at the end by default', () => {
    expect(ids(insertStep(ABC, step('X'), 1))).toEqual(['A', 'X', 'B', 'C']);
    expect(ids(insertStep(ABC, step('X')))).toEqual(['A', 'B', 'C', 'X']);
  });

  it('clamps a nonsensical rank rather than leaving a hole in the list', () => {
    expect(ids(insertStep(ABC, step('X'), 99))).toEqual(['A', 'B', 'C', 'X']);
    expect(ids(insertStep(ABC, step('X'), -5))).toEqual(['X', 'A', 'B', 'C']);
  });

  it('removes by rank, and ignores an unknown rank', () => {
    expect(ids(removeStep(ABC, 1))).toEqual(['A', 'C']);
    expect(ids(removeStep(ABC, 7))).toEqual(['A', 'B', 'C']);
  });
});

describe('open documents', () => {
  it('opens only one tab per library entry', () => {
    const first = adoptContainer('my recipe', ABC);
    expect(adoptContainer('my recipe', ABC)).toBe(first);
    closeContainer(first);
  });

  it('marks itself "modified" as soon as a step is touched, and forgets it on save', () => {
    const id = newContainer();
    expect(containerById(id)?.dirty).toBe(false);

    setSteps(id, ABC);
    expect(containerById(id)?.dirty).toBe(true);
    expect(ids(containerById(id)!.steps as Step[])).toEqual(['A', 'B', 'C']);

    markContainerSaved(id, 'my recipe');
    expect(containerById(id)?.dirty).toBe(false);
    expect(containerById(id)?.title).toBe('my recipe');
    closeContainer(id);
  });

  it('keeps a stable tab id when the name changes', () => {
    // The name is the library entry, the id is the dockview tab: tying them together would make
    // the tab disappear and reappear on the first save.
    const id = newContainer();
    markContainerSaved(id, 'named at last');
    expect(containerById(id)?.id).toBe(id);
    closeContainer(id);
  });
});

describe('step flags', () => {
  it('carries them along on a move', () => {
    // This is why the flags live **on** the step rather than in parallel arrays: `moveStep` has
    // nothing to know about them, and therefore cannot shift them out of alignment.
    const flagged = setStepMask(setStepEnabled(ABC, 0, false), 0, 'Mask01', true);
    const moved = moveStep(flagged, 0, 2);
    expect(ids(moved)).toEqual(['B', 'C', 'A']);
    expect(moved[2]).toMatchObject({ enabled: false, mask: 'Mask01', mask_inverted: true });
    expect(moved[0]?.enabled).toBeUndefined();
  });

  it('deletes the key rather than writing the default value', () => {
    // A recipe with no flags must serialize exactly as it did before this change: `enabled: true`
    // on the wire would show up as a diff in every XML already saved.
    const disabled = setStepEnabled(ABC, 1, false);
    expect(disabled[1]?.enabled).toBe(false);
    const reenabled = setStepEnabled(disabled, 1, true);
    expect('enabled' in reenabled[1]!).toBe(false);
  });

  it('removing the mask takes its inversion flag with it', () => {
    const masked = setStepMask(ABC, 0, 'Mask01', true);
    const unmasked = setStepMask(masked, 0, null);
    expect('mask' in unmasked[0]!).toBe(false);
    expect('mask_inverted' in unmasked[0]!).toBe(false);
  });

  it('isEnabled treats a missing key as "enabled"', () => {
    expect(isEnabled({ process_id: 'A', values: {} })).toBe(true);
    expect(isEnabled({ process_id: 'A', values: {}, enabled: false })).toBe(false);
  });

  it('ignores an out-of-range index without damaging the list', () => {
    expect(ids(setStepEnabled(ABC, 9, false))).toEqual(['A', 'B', 'C']);
    expect(ids(setStepMask(ABC, -1, 'M'))).toEqual(['A', 'B', 'C']);
  });
});
