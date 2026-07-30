// Logic of the frame selector — the rendering is covered by the Playwright smoke.
//
// The judging rules (normalisation, expressions, weight floor) live in the domain and are
// covered by pytest. What is tested here is what the client makes of them: the sorting, the
// numbering, how rejection reasons are read, and the bounds of the plots.

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const selector = await import('../src/pipeline/selector');

type Measurement = import('../src/pipeline/selector').Measurement;
type MeasuresPayload = import('../src/pipeline/selector').MeasuresPayload;

const GROUP = 'light_L_300s_bin1_g100_m10C';

function measurement(index: number, over: Partial<Measurement> = {}): Measurement {
  return {
    frame: `/data/light_${String(index).padStart(3, '0')}.fits`,
    stars: 100 + index,
    fwhm: 5 - 0.5 * index,
    eccentricity: 0.4,
    snr: 10 + index,
    noise: 0.001,
    median: 0.01,
    score: 70,
    weight: 0.25,
    approved: true,
    ...over,
  };
}

function load(rows: Measurement[], over: Partial<MeasuresPayload> = {}): void {
  selector.measures.value = {
    groups: { [GROUP]: rows },
    rejects: { [GROUP]: [] },
    criteria: {
      [GROUP]: { approval: '', weighting: '', min_weight: 0.05, roundness_limit: 3 },
    },
    summary: [
      {
        key: GROUP,
        filter: 'L',
        path: '/out/integrated/L.fits',
        exposure: 300,
        planned: rows.length,
        measured: rows.length,
        frames: rows.filter((r) => r.approved).length,
        rejected: rows.filter((r) => !r.approved).length,
        rejected_by: {},
        integration: rows.filter((r) => r.approved).length * 300,
      },
    ],
    ...over,
  };
}

beforeEach(() => {
  selector.measures.value = null;
  selector.activeGroup.value = '';
  selector.sortKey.value = 'index';
  selector.sortAscending.value = true;
  selector.selectedFrame.value = '';
});

describe('current group', () => {
  it('picks the first group that has measurements', () => {
    selector.measures.value = {
      groups: { empty: [], [GROUP]: [measurement(0)] },
      rejects: {},
      criteria: {},
      summary: [],
    };

    expect(selector.currentGroup.value).toBe(GROUP);
  });

  it('falls back to an existing group when the chosen one is gone', () => {
    // The plan has been regenerated in the meantime: keeping a dead key would empty the
    // screen without saying a word.
    load([measurement(0)]);
    selector.activeGroup.value = 'deleted_group';

    expect(selector.currentGroup.value).toBe(GROUP);
  });
});

describe('sorting', () => {
  it('keeps the original rank whatever the displayed order', () => {
    // That rank pairs a measurement with its frame on the domain side: renumbering it would
    // make the "#" column point at a different frame depending on the sort.
    load([measurement(0), measurement(1), measurement(2)]);
    selector.sortKey.value = 'fwhm';

    const order = selector.sortedRows.value;
    expect(order.map((row) => row.index)).toEqual([2, 1, 0]);
    expect(order[0]!.row.frame).toBe('/data/light_002.fits');
  });

  it('flips the direction when the same column is clicked again', () => {
    load([measurement(0), measurement(1)]);

    selector.toggleSort('snr');
    expect(selector.sortAscending.value).toBe(true);
    selector.toggleSort('snr');
    expect(selector.sortAscending.value).toBe(false);
  });

  it('starts ascending again on a change of column', () => {
    load([measurement(0)]);
    selector.toggleSort('snr');
    selector.toggleSort('snr');

    selector.toggleSort('fwhm');

    expect([selector.sortKey.value, selector.sortAscending.value]).toEqual(['fwhm', true]);
  });

  it('sorts file names as text, not as numbers', () => {
    load([measurement(2), measurement(10), measurement(1)]);
    selector.sortKey.value = 'name';

    expect(selector.sortedRows.value.map((row) => selector.basename(row.row.frame))).toEqual([
      'light_001.fits',
      'light_002.fits',
      'light_010.fits',
    ]);
  });
});

describe('cells', () => {
  it('shows a rejection reason only on a dropped frame', () => {
    const kept = measurement(0);
    const dropped = measurement(1, { approved: false, rejected_by: 'manual' });
    load([kept, dropped]);

    expect(selector.cellValue(kept, 0, 'rejected_by')).toBe('');
    expect(selector.cellValue(dropped, 1, 'rejected_by')).toBe('manual');
  });

  it('names the reason even when the domain gave none', () => {
    // A dropped frame with no reason would be the worst of both worlds: gone from the stack
    // and silent about why.
    const orphan = measurement(0, { approved: false });
    load([orphan]);

    expect(selector.cellValue(orphan, 0, 'rejected_by')).toBe('unknown');
  });

  it('renders the index and the name, which are not in the measurement', () => {
    const row = measurement(7);
    load([row]);

    expect(selector.cellValue(row, 3, 'index')).toBe(3);
    expect(selector.cellValue(row, 0, 'name')).toBe('light_007.fits');
  });
});

describe('plot bounds', () => {
  it('brackets the values of the batch', () => {
    load([measurement(0), measurement(1), measurement(2)]);

    expect(selector.metricRange('fwhm')).toEqual({ min: 4, max: 5 });
  });

  it('gives some room to a perfectly uniform batch', () => {
    // Otherwise the scatter flattens onto a line and the scale becomes a division by zero.
    load([measurement(0, { fwhm: 3 }), measurement(1, { fwhm: 3 })]);

    expect(selector.metricRange('fwhm')).toEqual({ min: 2.5, max: 3.5 });
  });

  it('stays defined with no measurement at all', () => {
    load([]);

    expect(selector.metricRange('fwhm')).toEqual({ min: 0, max: 1 });
  });
});

describe('rejections', () => {
  it('tells a manual rejection from a criterion-driven one', () => {
    const manual = measurement(0, { approved: false, rejected_by: 'manual' });
    const automatic = measurement(1, { approved: false, rejected_by: 'min_weight' });
    load([manual, automatic], {
      rejects: { [GROUP]: [manual.frame] },
    } as Partial<MeasuresPayload>);

    expect(selector.isManuallyRejected(manual.frame)).toBe(true);
    expect(selector.isManuallyRejected(automatic.frame)).toBe(false);
  });
});

describe('availability', () => {
  it('reports the absence of measurements rather than showing an empty table', () => {
    selector.measures.value = { groups: { a: [], b: [] }, rejects: {}, criteria: {}, summary: [] };

    expect(selector.hasMeasures.value).toBe(false);
  });

  it('becomes available as soon as a single group is measured', () => {
    selector.measures.value = {
      groups: { a: [], b: [measurement(0)] },
      rejects: {},
      criteria: {},
      summary: [],
    };

    expect(selector.hasMeasures.value).toBe(true);
  });
});

describe('reference frame', () => {
  it('is derived from the run report', async () => {
    // It is the exposure that fixes the geometry of the whole group: the only one whose
    // identity changes the result of the others, hence the one to see before dropping it.
    const model = await import('../src/pipeline/model');
    model.report.value = {
      output_dir: '/out',
      results: [],
      executed: [],
      skipped: [],
      reference: '/data/light_002.fits',
      notes: [],
      products: [],
    };

    expect(selector.referenceFrame.value).toBe('/data/light_002.fits');
    model.report.value = null;
    expect(selector.referenceFrame.value).toBe('');
  });
});

describe('visible columns', () => {
  it('hides the quantities no measurement carries', () => {
    // A measurement file written before PSF fitting existed has neither `psf_count` nor the
    // field dispersions. A column of dashes would suggest a value of zero — which, on a
    // dispersion, reads as "perfect".
    load([measurement(0), measurement(1)]);

    const ids = selector.visibleColumns.value.map((c) => c.id);
    expect(ids).not.toContain('psf_count');
    expect(ids).not.toContain('fwhm_arcsec');
    expect(ids).toContain('fwhm');
  });

  it('shows the ones the measurements do carry', () => {
    load([
      measurement(0, { psf_count: 42, fwhm_arcsec: 1.9, fwhm_mean_dev: 0.1 }),
      measurement(1, { psf_count: 38, fwhm_arcsec: 2.0, fwhm_mean_dev: 0.2 }),
    ]);

    const ids = selector.visibleColumns.value.map((c) => c.id);
    expect(ids).toContain('psf_count');
    expect(ids).toContain('fwhm_arcsec');
    expect(ids).toContain('fwhm_mean_dev');
  });

  it('needs a single measurement to carry it', () => {
    // An exposure with no fittable star must not make the column disappear for the others.
    load([measurement(0), measurement(1, { psf_count: 12 })]);

    expect(selector.visibleColumns.value.map((c) => c.id)).toContain('psf_count');
  });

  it('keeps every column when there is nothing to show', () => {
    load([]);

    expect(selector.visibleColumns.value.length).toBe(selector.COLUMNS.length);
  });
});
