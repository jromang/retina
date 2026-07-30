// Logic of the pre-processing wizard — the rendering is tested by the Playwright smoke.
//
// The astro rules (grouping, master matching, sizes) live in the domain and are covered by
// pytest. What is tested here is what the client makes of them: the translation into table
// rows, the formatting, and whatever it adds of its own.

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const model = await import('../src/pipeline/model');
const { client } = await import('../src/api/client');
const { jobs } = await import('../src/processes/jobs');

type FrameInfo = import('../src/pipeline/model').FrameInfo;

function frame(over: Partial<FrameInfo> = {}): FrameInfo {
  return {
    path: '/data/x.fits',
    kind: 'light',
    filter: 'L',
    exposure: 300,
    binning: 1,
    temperature: -10,
    gain: 100,
    width: 100,
    height: 100,
    bayer: null,
    source: 'header',
    excluded: false,
    ...over,
  };
}

function setInventory(frames: FrameInfo[]) {
  model.inventory.value = { root: '/data', frames };
}

type GroupInfo = import('../src/pipeline/model').GroupInfo;
type CalibrationMatch = import('../src/pipeline/model').CalibrationMatch;

function group(over: Partial<GroupInfo> = {}): GroupInfo {
  const frames = over.frames ?? [frame()];
  return {
    key: 'light_L_300s_bin1_g100_m10C',
    kind: 'light',
    filter: 'L',
    exposure: 300,
    binning: 1,
    temperature: -10,
    gain: 100,
    ...over,
    frames,
    count: frames.length,
  };
}

function match(over: Partial<CalibrationMatch> = {}): CalibrationMatch {
  return {
    target: 'light_L_300s_bin1_g100_m10C',
    bias: null,
    dark: null,
    flat: null,
    dark_scale: 1,
    chain: [],
    notes: [],
    ...over,
  };
}

type PlanInfo = import('../src/pipeline/model').PlanInfo;

function planInfo(over: Partial<PlanInfo> = {}): PlanInfo {
  return {
    version: '1.0',
    root: '/data',
    output_dir: '/data/out',
    preset: { name: 'auto' },
    notes: [],
    products: [],
    disk: { stages: {}, total_bytes: 0, free_bytes: null },
    steps: [],
    ...over,
  };
}

/** Installs the grouping the domain returned, and the matching inventory. */
function show(groups: GroupInfo[], matches: Record<string, CalibrationMatch> = {}) {
  setInventory(groups.flatMap((g) => g.frames));
  model.survey.value = { groups, matches };
}

beforeEach(() => {
  model.reset();
  model.folder.value = '';
  jobs.value = {};
});

// The grouping itself is done by the domain (covered by pytest): what is tested here is the
// translation into table rows, and what the client adds of its own.
describe('groupRows', () => {
  it('reuses the domain keys rather than a recomputed grouping', () => {
    show([group({ key: 'light_Ha_600s_bin2_g0_m15C' })]);

    expect(model.groupRows.value.map((r) => r.key)).toEqual(['light_Ha_600s_bin2_g0_m15C']);
  });

  it('shows no exposure for a flat', () => {
    show([group({ kind: 'flat', key: 'flat_L_bin1_g100_m10C', exposure: 2 })]);

    expect(model.groupRows.value[0]?.exposure).toBeNull();
  });

  it('flags a classification inferred from the file name', () => {
    show([group({ frames: [frame({ source: 'filename' })] })]);

    expect(model.groupRows.value[0]?.guessed).toBe(true);
  });

  it('stops flagging a classification corrected by hand', () => {
    show([group({ frames: [frame({ source: 'user' })] })]);

    expect(model.groupRows.value[0]?.guessed).toBe(false);
  });

  it('carries the frame paths — corrections are applied to them', () => {
    show([group({ frames: [frame({ path: '/a.fits' }), frame({ path: '/b.fits' })] })]);

    expect(model.groupRows.value[0]?.paths).toEqual(['/a.fits', '/b.fits']);
  });

  it('counts unclassified frames separately', () => {
    show([group()]);
    setInventory([...(model.inventory.value?.frames ?? []), frame({ kind: 'unknown', path: '/z.fits' })]);

    expect(model.groupRows.value).toHaveLength(1);
    expect(model.unknownFrames.value).toHaveLength(1);
  });

  it('adds back the dropped groups, which the domain no longer forms', () => {
    // Without this, dropping a group would make it vanish from the screen — hence from any
    // possibility of bringing it back.
    model.survey.value = { groups: [], matches: {} };
    setInventory([
      frame({ path: '/a.fits', excluded: true }),
      frame({ path: '/b.fits', excluded: true }),
    ]);

    expect(model.groupRows.value).toHaveLength(1);
    expect(model.groupRows.value[0]?.excluded).toBe(true);
    expect(model.groupRows.value[0]?.count).toBe(2);
  });

  it('orders lights, flats, darks, bias', () => {
    show([
      group({ kind: 'bias', key: 'bias_bin1_g100_m10C' }),
      group({ kind: 'dark', key: 'dark_300s_bin1_g100_m10C' }),
      group({ kind: 'flat', key: 'flat_L_bin1_g100_m10C' }),
      group({ kind: 'light', key: 'light_L_300s_bin1_g100_m10C' }),
    ]);

    expect(model.groupRows.value.map((r) => r.kind)).toEqual(['light', 'flat', 'dark', 'bias']);
  });
});

describe('calibrationSummary', () => {
  const summary = (kind: GroupInfo['kind'], m: Partial<CalibrationMatch>) => {
    show([group({ kind })], { [group({ kind }).key]: match(m) });
    return model.calibrationSummary(model.groupRows.value[0]!);
  };

  it('lists the masters that were selected', () => {
    expect(summary('light', { dark: 'd', flat: 'f' })?.has).toBe('dark + flat');
  });

  it('states the factor when the dark is scaled', () => {
    expect(summary('light', { bias: 'b', dark: 'd', dark_scale: 0.5 })?.has).toBe(
      'bias + dark ×0.50',
    );
  });

  it('reports what a light is missing', () => {
    expect(summary('light', { dark: 'd' })?.missing).toEqual(['flat']);
  });

  it('does not ask for a bias when a dark already contains one', () => {
    // Standard pre-processing rule: a master dark carries the bias, so omitting it is
    // deliberate. Reporting it would send the user hunting for a problem that does not exist.
    expect(summary('light', { dark: 'd', flat: 'f' })?.missing).toEqual([]);
  });

  it('does not ask for a flat on a group of flats', () => {
    expect(summary('flat', { bias: 'b' })?.missing).toEqual([]);
  });

  it('reports a flat with nothing to calibrate it', () => {
    expect(summary('flat', {})?.missing).toEqual(['bias']);
  });

  it('says nothing about a dark or a bias, which are not calibrated', () => {
    show([group({ kind: 'dark', key: 'dark_300s_bin1_g100_m10C' })]);

    expect(model.calibrationSummary(model.groupRows.value[0]!)).toBeNull();
  });
});

describe('groupWarnings', () => {
  it('surfaces the matching notes together with their group', () => {
    const g = group();
    show([g], { [g.key]: match({ notes: ['dark too far off in exposure'] }) });

    expect(model.groupWarnings.value).toEqual([
      { key: g.key, note: 'dark too far off in exposure' },
    ]);
  });

  it('says nothing when all is well', () => {
    const g = group();
    show([g], { [g.key]: match({ dark: 'd', flat: 'f' }) });

    expect(model.groupWarnings.value).toEqual([]);
  });
});

describe('stage', () => {
  it('starts at the folder choice', () => {
    expect(model.stage.value).toBe('folder');
  });

  it('moves to "scanned" as soon as an inventory arrives', () => {
    setInventory([frame()]);

    expect(model.stage.value).toBe('scanned');
  });

  it('moves to "planned" once the plan is there', () => {
    setInventory([frame()]);
    model.plan.value = planInfo();

    expect(model.stage.value).toBe('planned');
  });

  it('moves to "running" while the job runs, whatever else holds', () => {
    model.jobId.value = 'j1';
    jobs.value = {
      j1: {
        id: 'j1',
        process_id: 'Pipeline',
        view: null,
        state: 'running',
        fraction: 0.3,
        message: 'frame 2/8',
      },
    };

    expect(model.running.value).toBe(true);
    expect(model.stage.value).toBe('running');
    expect(model.job.value?.fraction).toBe(0.3);
  });

  it('tracks the job by id, not by process name', () => {
    // two successive runs of the pipeline must not be confused with one another
    model.jobId.value = 'j2';
    jobs.value = {
      j1: {
        id: 'j1',
        process_id: 'Pipeline',
        view: null,
        state: 'running',
        fraction: 0.9,
        message: 'stale',
      },
    };

    expect(model.job.value).toBeNull();
  });
});

describe('formatting', () => {
  it('gives seconds below the minute, minutes beyond', () => {
    expect(model.formatDuration(45)).toBe('45 s');
    expect(model.formatDuration(1200)).toBe('20 min');
  });

  it('switches to hours when "200 min" would stop being readable', () => {
    expect(model.formatDuration(12000)).toBe('3 h 20');
    expect(model.formatDuration(3600)).toBe('1 h 00');
  });

  it('makes up no duration when the exposure is unknown', () => {
    expect(model.formatDuration(null)).toBe('—');
  });

  it('counts bytes in decimal units, the ones disks use', () => {
    expect(model.formatBytes(1000)).toBe('1.0 kB');
    expect(model.formatBytes(412_000_000_000)).toBe('412 GB');
    expect(model.formatBytes(0)).toBe('0 B');
  });
});

describe('plan summary', () => {
  const product = (over = {}) => ({
    key: 'light_L_300s',
    filter: 'L',
    frames: 4,
    exposure: 300,
    path: '/data/out/L.fits',
    integration: 1200,
    ...over,
  });

  it('adds up the exposure of every final image', () => {
    model.plan.value = planInfo({
      products: [product(), product({ key: 'light_Ha_300s', filter: 'Ha', integration: 600 })],
    });

    expect(model.totalIntegration.value).toBe(1800);
  });

  it('announces no total when no exposure is known', () => {
    model.plan.value = planInfo({ products: [product({ exposure: null, integration: null })] });

    expect(model.totalIntegration.value).toBeNull();
  });

  it('reports a disk that is too small before the run, not after', () => {
    model.plan.value = planInfo({
      disk: { stages: {}, total_bytes: 412_000_000_000, free_bytes: 180_000_000_000 },
    });

    expect(model.diskShort.value).toBe(true);
  });

  it('keeps quiet when the free space is unknown', () => {
    model.plan.value = planInfo({
      disk: { stages: {}, total_bytes: 412_000_000_000, free_bytes: null },
    });

    expect(model.diskShort.value).toBe(false);
  });
});

// --- editing the plan --------------------------------------------------------------------
//
// The contract is the same as for frame selection: the plan travels both ways, the server
// validates and echoes, the client reassigns whatever it receives. So what is tested here is
// the absence of local mutation — a refusal must leave the display on the plan's real state,
// not on what was just typed.

describe('editing a plan step', () => {
  const step = {
    id: 'calibrate_light_L',
    kind: 'per_frame' as const,
    label: 'Calibrate',
    group: 'light_L',
    inputs: ['/data/a.fits'],
    outputs: ['/out/a.fits'],
    bindings: {},
    processes: [{ process_id: 'ImageCalibration', values: { pedestal_mode: 'auto' } }],
  };

  it('adopts the plan the server returned, without editing it locally', async () => {
    model.plan.value = planInfo({ steps: [step] });
    const returned = planInfo({
      steps: [{ ...step, processes: [{ process_id: 'ImageCalibration',
                                       values: { pedestal_mode: 'none' } }] }],
    });
    const calls: unknown[] = [];
    const spy = vi
      .spyOn(client, 'call')
      .mockImplementation(async (method: string, params?: unknown) => {
        calls.push({ method, params });
        return returned as never;
      });

    await model.setStepParams('calibrate_light_L', 0, { pedestal_mode: 'none' });

    expect(calls).toEqual([
      {
        method: 'pipeline.set_step_params',
        params: {
          plan: planInfo({ steps: [step] }),
          step_id: 'calibrate_light_L',
          index: 0,
          values: { pedestal_mode: 'none' },
        },
      },
    ]);
    expect(model.plan.value?.steps[0]?.processes[0]?.values.pedestal_mode).toBe('none');
    spy.mockRestore();
  });

  it('leaves the plan untouched when the server refuses', async () => {
    const initial = planInfo({ steps: [step] });
    model.plan.value = initial;
    const spy = vi
      .spyOn(client, 'call')
      .mockRejectedValue(new Error('pedestal_mode: wildguess is not one of'));

    await model.setStepParams('calibrate_light_L', 0, { pedestal_mode: 'wildguess' });

    expect(model.plan.value).toEqual(initial);
    expect(model.error.value).toContain('is not one of');
    spy.mockRestore();
  });

  it('clears the report: it described the previous plan', async () => {
    model.plan.value = planInfo({ steps: [step] });
    model.report.value = { output_dir: '/out', results: [] } as never;
    const spy = vi
      .spyOn(client, 'call')
      .mockResolvedValue(planInfo({ steps: [step] }) as never);

    await model.setHooks('calibrate_light_L', { after: '/scripts/x.py' });

    expect(model.report.value).toBeNull();
    spy.mockRestore();
  });

  it('sends the preset along with the survey — otherwise table and plan would group differently', async () => {
    // The survey is refreshed after every correction to the inventory; we therefore go through
    // a public gesture rather than exporting the internal function for the test's sake.
    setInventory([frame()]);
    model.preset.value = 'seestar';
    const calls: { method: string; params?: unknown }[] = [];
    const spy = vi
      .spyOn(client, 'call')
      .mockImplementation(async (method: string, params?: unknown) => {
        calls.push({ method, params });
        return (method === 'pipeline.survey'
          ? { groups: [], matches: {} }
          : model.inventory.value) as never;
      });

    await model.setExcluded(['/data/x.fits'], true);

    const surveys = calls.filter((a) => a.method === 'pipeline.survey');
    expect(surveys).toHaveLength(1);
    expect((surveys[0]?.params as { preset?: string }).preset).toBe('seestar');
    spy.mockRestore();
  });
});
