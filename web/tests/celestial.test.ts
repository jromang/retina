// Sexagesimal formatting of celestial coordinates.
//
// All the interest is at the edges: rounding carry (59.999″ must not display as 60″), crossing
// the prime meridian, and the sign of the declination — three mistakes that yield a *plausible*
// but wrong coordinate, hence invisible on proofreading.

import { describe, expect, it } from 'vitest';

import { formatCelestial, formatDec, formatRa } from '../src/viewport/celestial';

describe('right ascension', () => {
  it('converts degrees into hours (15° = 1h)', () => {
    expect(formatRa(0)).toBe('00h00m00.00s');
    expect(formatRa(15)).toBe('01h00m00.00s');
    expect(formatRa(180)).toBe('12h00m00.00s');
  });

  it('splits out minutes and seconds', () => {
    // 10h21m30s = (10 + 21/60 + 30/3600) × 15°
    expect(formatRa((10 + 21 / 60 + 30 / 3600) * 15)).toBe('10h21m30.00s');
  });

  it('carries the rounding instead of showing 60 seconds', () => {
    // The case that gives a naive implementation away: rounding separately produces "59m60.00s".
    const justBefore = (12 + 59 / 60 + 59.999 / 3600) * 15;
    expect(formatRa(justBefore)).toBe('13h00m00.00s');
  });

  it('brings an out-of-turn angle back into [0h, 24h)', () => {
    expect(formatRa(-15)).toBe('23h00m00.00s');
    expect(formatRa(375)).toBe('01h00m00.00s');
    // Exactly 360° closes the turn at 0h, not at 24h.
    expect(formatRa(360)).toBe('00h00m00.00s');
  });
});

describe('declination', () => {
  it('always carries its sign, including near zero', () => {
    // An unsigned declination is ambiguous: +0°30′ and −0°30′ are one degree apart.
    expect(formatDec(0.5)).toBe('+00°30′00.0″');
    expect(formatDec(-0.5)).toBe('−00°30′00.0″');
  });

  it('reaches the poles', () => {
    expect(formatDec(90)).toBe('+90°00′00.0″');
    expect(formatDec(-90)).toBe('−90°00′00.0″');
  });

  it('carries the rounding onto the minutes and then the degrees', () => {
    expect(formatDec(41 + 59 / 60 + 59.99 / 3600)).toBe('+42°00′00.0″');
  });

  it('splits out a typical declination (M31: +41°16′09″)', () => {
    expect(formatDec(41 + 16 / 60 + 9 / 3600)).toBe('+41°16′09.0″');
  });
});

describe('both together', () => {
  it('produces the form shown in the status bar', () => {
    // M31: α 00h42m44s, δ +41°16′09″
    expect(formatCelestial(10.6847, 41.2691)).toBe('α 00h42m44.33s  δ +41°16′08.8″');
  });
});
