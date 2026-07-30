// Plurals for counted messages — the CLDR rule of the current language, not `count > 1`.
//
// The subtlety that motivated this module: in English zero is plural ("0 stars") but in French
// zero is singular ("0 etoile"). The `count > 1` branches scattered across the panels were
// therefore wrong in both languages at once. `Intl.PluralRules` carries those rules natively —
// no need for Paraglide's ICU variants for two languages.
//
// Usage: `plural(n, m.psf_star_one({ count: n }), m.psf_star_many({ count: n }))` — both
// messages are evaluated (pure functions, zero cost), the rule picks which one to display.

import { getLocale } from '../paraglide/runtime';

const rules = new Map<string, Intl.PluralRules>();

export function plural(count: number, one: string, many: string, locale?: string): string {
  const langue = locale ?? getLocale();
  let regle = rules.get(langue);
  if (!regle) {
    regle = new Intl.PluralRules(langue);
    rules.set(langue, regle);
  }
  return regle.select(count) === 'one' ? one : many;
}
