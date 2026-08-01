// The tooltip a generated field actually shows.
//
// Its own module, small on purpose: `fields`, `editors` and `CurveEditor` all need it, and
// `fields` already imports the other two — putting it there would have made the cycle a real
// one rather than a type-only one.

import { m } from '../paraglide/messages';
import type { ParameterMeta } from '../api/types';

/**
 * The tooltip a field actually shows: the author's, plus what the schema already knows.
 *
 * 41 of the catalogue's 532 parameters carry a written tooltip, so hovering nine fields out of
 * ten produced nothing at all — while the schema held, all along, the two facts one hovers to
 * check: what the default is (is this value mine, or the one it came with?) and how far the
 * parameter goes. Writing the other 491 tooltips is an editorial job; showing what is already
 * known costs one function, translated once.
 *
 * Composite types are left out: "default []" says nothing a reader did not already see.
 */
export function fieldTitle(param: ParameterMeta): string {
  const lines = param.tooltip ? [param.tooltip] : [];
  const facts: string[] = [];
  const scalar =
    typeof param.default === 'number' ||
    typeof param.default === 'boolean' ||
    (typeof param.default === 'string' && param.default !== '');
  if (scalar) facts.push(m.field_default({ value: String(param.default) }));
  if (param.min !== null && param.max !== null) {
    facts.push(m.field_range({ min: String(param.min), max: String(param.max) }));
  }
  if (facts.length) lines.push(facts.join(' · '));
  return lines.join('\n');
}
