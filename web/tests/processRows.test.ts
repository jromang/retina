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

describe('search reaches beyond the class name', () => {
  const RICH = [
    {
      category: 'BackgroundModelization',
      items: [
        {
          process_id: 'BackgroundExtraction',
          category: 'BackgroundModelization',
          keywords: ['gradient', 'pollution lumineuse', 'fond de ciel'],
        } as ProcessMeta,
      ],
    },
    {
      category: 'IntensityTransformations',
      items: [
        {
          process_id: 'AutoHistogram',
          category: 'IntensityTransformations',
          keywords: ['étirement', 'auto-stretch'],
        } as ProcessMeta,
      ],
    },
  ];

  it('finds a process by a documentation keyword', () => {
    // The whole point: "gradient" used to find `GradientCorrection` and miss the process
    // people actually reach for.
    const rows = processRows(RICH, 'gradient');
    expect(rows.filter((r) => r.kind === 'item')).toHaveLength(1);
    expect(rows[1]).toMatchObject({ process: { process_id: 'BackgroundExtraction' } });
  });

  it('ignores accents in the keywords too', () => {
    expect(processRows(RICH, 'etirement').filter((r) => r.kind === 'item')).toHaveLength(1);
  });

  it('finds a process by its category', () => {
    const rows = processRows(RICH, 'intensity');
    expect(rows.filter((r) => r.kind === 'item')).toHaveLength(1);
  });

  it('matches nothing rather than everything when nothing matches', () => {
    expect(processRows(RICH, 'zzz')).toEqual([]);
  });
});

describe('recently used', () => {
  it('puts them first without removing them from their category', () => {
    // A list whose items move depending on what one did an hour ago cannot be learned: the
    // recent group is a shortcut laid on top, not a reordering.
    const rows = processRows(GROUPS, '', ['UnsharpMask']);
    const items = rows.filter((r) => r.kind === 'item');

    expect(rows[0]).toMatchObject({ kind: 'header', count: 1 });
    expect(items).toHaveLength(4);
    expect(items.filter((r) => r.process.process_id === 'UnsharpMask')).toHaveLength(2);
    expect(items[0]).toMatchObject({ recent: true });
  });

  it('honours the search filter, and ignores a process that no longer exists', () => {
    expect(processRows(GROUPS, 'histo', ['UnsharpMask'])).toHaveLength(2);
    expect(processRows(GROUPS, '', ['Vanished'])[0]).toMatchObject({ category: 'Convolution' });
  });
});
