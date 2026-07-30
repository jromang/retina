// Job progress in the status bar.
//
// Reads `activeJobs` (queued|running only): insensitive to the `forget()` that clears the
// finished jobs — their durable trace is the notification center, not this bar.
// One job: spinner + name + mini bar + cancel. Several: the first one + a "+N" that
// unfolds the list, each one cancellable.

import { useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { activeJobs, cancelJob, type JobState } from '../processes/jobs';

function Bar({ fraction }: { fraction: number | null }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: '70px',
        height: '3px',
        background: 'var(--vscode-input-border, #3c3c3c)',
        verticalAlign: 'middle',
      }}
    >
      <span
        style={{
          display: 'block',
          height: '100%',
          // Full and dimmed bar when the process does not instrument its loops:
          // "it is running", without claiming to know more.
          width: fraction === null ? '100%' : `${Math.round(fraction * 100)}%`,
          background: 'var(--vscode-progressBar-background, #0e70c0)',
          opacity: fraction === null ? 0.45 : 1,
        }}
      />
    </span>
  );
}

function JobRow({ job }: { job: JobState }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }} title={job.message}>
      <i class="codicon codicon-loading codicon-modifier-spin" aria-hidden="true" />
      <span>{job.process_id}</span>
      <Bar fraction={job.fraction} />
      <button
        title={m.status_cancel_job()}
        aria-label={m.status_cancel_job()}
        onClick={() => cancelJob(job.id)}
        style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', padding: 0 }}
      >
        <i class="codicon codicon-close" aria-hidden="true" />
      </button>
    </span>
  );
}

export function JobsIndicator() {
  const [open, setOpen] = useState(false);
  const jobs = activeJobs.value;
  const first = jobs[0];
  if (!first) return null;

  return (
    <span class="status-item" style={{ position: 'relative' }}>
      <JobRow job={first} />
      {jobs.length > 1 && (
        <button
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          style={{
            background: 'none',
            border: 'none',
            color: 'inherit',
            cursor: 'pointer',
            marginLeft: '4px',
          }}
        >
          {m.status_jobs_more({ count: jobs.length - 1 })}
        </button>
      )}
      {open && jobs.length > 1 && (
        <div
          class="popover"
          onMouseLeave={() => setOpen(false)}
          style={{
            position: 'absolute',
            bottom: '100%',
            left: 0,
            zIndex: 50,
            padding: '8px',
            display: 'grid',
            gap: '6px',
            background: 'var(--vscode-menu-background, #252526)',
            border: '1px solid var(--vscode-menu-border, #454545)',
            borderRadius: '3px',
            fontSize: '12px',
            whiteSpace: 'nowrap',
          }}
        >
          {jobs.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
        </div>
      )}
    </span>
  );
}
