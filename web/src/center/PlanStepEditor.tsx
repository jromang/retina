// Editor for one step of the preprocessing plan.
//
// This was the last unticked box of automated preprocessing: the plan could be inspected but
// could only be adjusted from the console (`plan.steps[i].process.x = y`). The console
// contract remains true — it is pillar 2 — but having to go down there to change a rejection
// threshold was too high a step.
//
// Two design choices:
//
// 1. **The form is the processes' one** (`ParameterGrid`, the same as `ProcessPanel` and the
//    preferences panel). The parameter schema is the single source; a home-made rendering
//    would have diverged with the first field type added.
// 2. **An "Apply" button, not a send-per-keystroke.** One gesture = one call = one echo line
//    in the console, and a validation error arrives in one block rather than in a burst. It
//    is also what makes a clean refusal possible: the plan displayed stays the server's,
//    never a local draft that would look accepted.

import { useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { setHooks, setStepParams, type PlanStepInfo } from '../pipeline/model';
import { ParameterGrid } from '../processes/ParameterGrid';
import { askPath } from '../shell/native';
import { processes } from '../state/store';

/** Parameters the plan's graph computes — if editable, they would be overwritten or wrong. */
function verrous(step: PlanStepInfo): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [param, jeton] of Object.entries(step.bindings)) {
    out[param] = m.pipeline_param_bound({ token: jeton });
  }
  return out;
}

function ProcessForm({ step, index }: { step: PlanStepInfo; index: number }) {
  const process = step.processes[index];
  const valeurs = process?.values ?? {};
  const meta = processes.value.find((p) => p.process_id === process?.process_id);
  const [draft, setDraft] = useState<Record<string, unknown>>(valeurs);
  const [busy, setBusy] = useState(false);
  // The plan comes back from the server on every edit: compare against the plan, not against
  // a frozen initial state, otherwise the button would stay active after a successful apply.
  const modifie = Object.keys(draft).some(
    (key) => JSON.stringify(draft[key]) !== JSON.stringify(valeurs[key]),
  );

  if (!process || !meta) {
    return (
      <p style={{ fontSize: '12px', color: 'var(--vscode-descriptionForeground)' }}>
        {m.process_unknown({ id: process?.process_id ?? String(index) })}
      </p>
    );
  }

  const appliquer = () => {
    setBusy(true);
    void setStepParams(step.id, index, draft).finally(() => setBusy(false));
  };

  return (
    <div style={{ marginTop: '6px' }}>
      <div style={{ fontSize: '11px', color: 'var(--vscode-descriptionForeground)' }}>
        {process.process_id}
      </div>
      <ParameterGrid
        parameters={meta.parameters}
        values={draft}
        onChange={setDraft}
        readOnly={verrous(step)}
      />
      <div style={{ display: 'flex', gap: '6px', marginTop: '6px' }}>
        <button className="btn" disabled={!modifie || busy} onClick={appliquer}>
          {m.pipeline_apply_step()}
        </button>
        <button
          className="btn"
          disabled={!modifie || busy}
          onClick={() => setDraft(valeurs)}
        >
          {m.process_reset()}
        </button>
      </div>
    </div>
  );
}

function HookField({ step, phase }: { step: PlanStepInfo; phase: 'before' | 'after' }) {
  const courant = step.hooks?.[phase] ?? '';
  const choisir = async () => {
    const chemin = await askPath({
      title: phase === 'before' ? m.pipeline_hook_before() : m.pipeline_hook_after(),
      filters: [{ name: 'Python', extensions: ['py'] }],
    });
    if (chemin) await setHooks(step.id, { [phase]: chemin });
  };

  return (
    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginTop: '4px' }}>
      <span
        style={{
          fontSize: '12px',
          color: 'var(--vscode-descriptionForeground)',
          minWidth: '60px',
        }}
      >
        {phase === 'before' ? m.pipeline_hook_before() : m.pipeline_hook_after()}
      </span>
      <span
        style={{
          flex: 1,
          fontSize: '11px',
          fontFamily: 'var(--retina-font-mono)',
          direction: 'rtl',
          textAlign: 'left',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={courant}
      >
        {courant || '—'}
      </span>
      <button className="btn" onClick={() => void choisir()}>
        {m.pipeline_hook_choose()}
      </button>
      {courant && (
        <button className="btn" onClick={() => void setHooks(step.id, { [phase]: null })}>
          {m.pipeline_hook_clear()}
        </button>
      )}
    </div>
  );
}

export function PlanStepEditor({ step }: { step: PlanStepInfo }) {
  return (
    <div
      style={{
        margin: '4px 0 8px',
        padding: '6px 8px',
        border: '1px solid var(--vscode-panel-border)',
        borderRadius: '3px',
      }}
    >
      {step.processes.length === 0 ? (
        <p style={{ fontSize: '12px', color: 'var(--vscode-descriptionForeground)', margin: 0 }}>
          {m.process_no_parameters()}
        </p>
      ) : (
        step.processes.map((process, index) => (
          <ProcessForm key={`${process.process_id}-${index}`} step={step} index={index} />
        ))
      )}
      <div style={{ marginTop: '8px', borderTop: '1px solid var(--vscode-panel-border)' }}>
        <p
          style={{
            fontSize: '11px',
            color: 'var(--vscode-descriptionForeground)',
            margin: '6px 0 0',
          }}
        >
          {m.pipeline_hooks_hint()}
        </p>
        <HookField step={step} phase="before" />
        <HookField step={step} phase="after" />
      </div>
    </div>
  );
}
