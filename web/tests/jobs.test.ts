// Hydrating jobs from the snapshot.
//
// The server was already publishing the `jobs` key, but the TS type ignored it: a client that
// reconnected during a run lost its progress bar and its Cancel button.

import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { JobSnapshot } from '../src/api/types';

// `api/client` reads the token when the module loads: it needs a plausible window.
vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const { hydrateJobs, jobs, activeJobs, jobFor } = await import('../src/processes/jobs');

function inFlight(over: Partial<JobSnapshot> = {}): JobSnapshot {
  return {
    id: 'j1',
    process_id: 'Integration',
    view: null,
    state: 'running',
    message: '',
    fraction: 0.4,
    progress_message: 'Reading 4/10',
    ...over,
  };
}

describe('hydrateJobs', () => {
  beforeEach(() => {
    jobs.value = {};
  });

  it('restores an in-flight job with its progress', () => {
    hydrateJobs([inFlight()]);

    expect(activeJobs.value).toHaveLength(1);
    expect(jobFor('Integration')?.fraction).toBe(0.4);
  });

  it('shows the current step rather than an empty error message', () => {
    hydrateJobs([inFlight()]);

    expect(jobFor('Integration')?.message).toBe('Reading 4/10');
  });

  it('falls back on the final message when there is one', () => {
    hydrateJobs([inFlight({ progress_message: '', message: 'ValueError: nothing to integrate' })]);

    expect(jobs.value['j1']?.message).toBe('ValueError: nothing to integrate');
  });

  it('is authoritative on in-flight jobs: the ones it no longer lists disappear', () => {
    hydrateJobs([inFlight({ id: 'j1' }), inFlight({ id: 'j2' })]);
    hydrateJobs([inFlight({ id: 'j2' })]);

    expect(Object.keys(jobs.value)).toEqual(['j2']);
  });

  it('keeps finished jobs, which the snapshot no longer mentions', () => {
    // long enough for their bar to show its final state
    jobs.value = {
      j9: { id: 'j9', process_id: 'X', view: null, state: 'error', fraction: null, message: 'boom' },
    };
    hydrateJobs([inFlight({ id: 'j1' })]);

    expect(Object.keys(jobs.value).sort()).toEqual(['j1', 'j9']);
    expect(jobs.value['j9']?.state).toBe('error');
  });

  it('accepts a snapshot with no job', () => {
    hydrateJobs([inFlight()]);
    hydrateJobs([]);

    expect(activeJobs.value).toEqual([]);
  });

  it('tolerates a missing fraction (uninstrumented process)', () => {
    hydrateJobs([inFlight({ fraction: null })]);

    expect(jobFor('Integration')?.fraction).toBeNull();
  });
});
