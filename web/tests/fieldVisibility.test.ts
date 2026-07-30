// Conditional visibility of a field in the auto-generated form. Pure logic, no DOM: this is
// what `BackgroundExtraction` uses to show the photutils settings only under the backend of the
// same name, and the AI model selector only under the `ai` backend.

import { describe, expect, it } from 'vitest';

import type { ParameterMeta } from '../src/api/types';

const { isVisible } = await import('../src/processes/fields');

function param(overrides: Partial<ParameterMeta>): ParameterMeta {
  return {
    id: 'p',
    type: 'str',
    default: '',
    min: null,
    max: null,
    choices: null,
    label: 'P',
    tooltip: '',
    ...overrides,
  };
}

describe('isVisible', () => {
  it('always shows a field with no clause', () => {
    expect(isVisible(param({}), { backend: 'ai' })).toBe(true);
    expect(isVisible(param({ visible_when: null }), {})).toBe(true);
  });

  it('gates a field on the value of the controlling parameter', () => {
    const box = param({ id: 'box_size', visible_when: { param: 'backend', values: ['photutils'] } });
    expect(isVisible(box, { backend: 'photutils' })).toBe(true);
    expect(isVisible(box, { backend: 'ai' })).toBe(false);
  });

  it('accepts several allowed values', () => {
    const p = param({ visible_when: { param: 'mode', values: ['a', 'b'] } });
    expect(isVisible(p, { mode: 'a' })).toBe(true);
    expect(isVisible(p, { mode: 'b' })).toBe(true);
    expect(isVisible(p, { mode: 'c' })).toBe(false);
  });

  it('compares through String() — a numeric controller does not yield a false negative', () => {
    const p = param({ visible_when: { param: 'n', values: [2] } });
    expect(isVisible(p, { n: 2 })).toBe(true);
    expect(isVisible(p, { n: '2' })).toBe(true);
    expect(isVisible(p, { n: 3 })).toBe(false);
  });

  it('hides the field when the controller is missing', () => {
    const p = param({ visible_when: { param: 'backend', values: ['ai'] } });
    expect(isVisible(p, {})).toBe(false);
  });
});
