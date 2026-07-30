// Pluralisation follows the CLDR rule of the language, not `count > 1` — and the difference
// shows at zero: English pluralises it, French keeps the singular. That is the bug the move to
// `plural()` fixed, and this test stops it from coming back.

import { describe, expect, it } from 'vitest';

import { plural } from '../src/ui/plural';

describe('plural', () => {
  it('English: zero is plural', () => {
    expect(plural(0, 'star', 'stars', 'en')).toBe('stars');
    expect(plural(1, 'star', 'stars', 'en')).toBe('star');
    expect(plural(2, 'star', 'stars', 'en')).toBe('stars');
  });

  it('French: zero is singular', () => {
    expect(plural(0, 'fichier', 'fichiers', 'fr')).toBe('fichier');
    expect(plural(1, 'fichier', 'fichiers', 'fr')).toBe('fichier');
    expect(plural(2, 'fichier', 'fichiers', 'fr')).toBe('fichiers');
  });
});
