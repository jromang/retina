// Flattening and windowing of the process explorer — the pure virtualisation logic, tested
// without a DOM. An arithmetic mistake here would show up as missing rows or as scrolling that
// lies about where it is.

import { describe, expect, it, vi } from 'vitest';

import type { ProcessMeta } from '../src/api/types';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const { processRows, rowWindow } = await import('../src/panels/processRows');

function meta(id: string): ProcessMeta {
  return { process_id: id } as ProcessMeta;
}

const GROUPS = [
  { category: 'Convolution', items: [meta('GaussianConvolution'), meta('UnsharpMask')] },
  { category: 'Stretch', items: [meta('HistogramTransformation')] },
];

describe('processRows', () => {
  it('flattens headers and items in order', () => {
    const rows = processRows(GROUPS, '');
    expect(rows.map((r) => (r.kind === 'header' ? r.category : r.process.process_id))).toEqual([
      'Convolution',
      'GaussianConvolution',
      'UnsharpMask',
      'Stretch',
      'HistogramTransformation',
    ]);
    expect(rows[0]).toEqual({ kind: 'header', category: 'Convolution', count: 2 });
  });

  it('filters case- and accent-insensitively, and drops emptied categories', () => {
    const rows = processRows(GROUPS, 'histo');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ kind: 'header', category: 'Stretch', count: 1 });
  });

  it('returns an empty list when nothing matches', () => {
    expect(processRows(GROUPS, 'zzz')).toEqual([]);
  });
});

describe('rowWindow', () => {
  it('covers the visible area plus the margin', () => {
    // 22 px per row, 220 px viewport: ~10 visible rows + 4 of margin on each side
    const { start, end } = rowWindow(220, 220, 100, 22);
    expect(start).toBe(6); // floor(220/22) - 4
    expect(end).toBe(24); // ceil(440/22) + 4
  });

  it('clamps to the bounds of the list', () => {
    expect(rowWindow(0, 220, 5, 22)).toEqual({ start: 0, end: 5 });
    // a stale scrollTop (list refiltered shorter) returns the tail, never emptiness
    expect(rowWindow(10_000, 220, 5, 22)).toEqual({ start: 4, end: 5 });
    expect(rowWindow(0, 220, 0, 22)).toEqual({ start: 0, end: 0 });
  });
});
