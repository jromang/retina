// Tool window of a process: auto-generated form + control bar.
//
// It follows the tool-window model the Qt shell already implemented: one window per process,
// singleton, applying to the **active view** — or to the one it is pointed at. The form comes
// entirely from the ``Parameter`` schema (see fields.tsx): no process has a hand-written UI.
//
// The control bar follows the Qt one, ⠿ "New instance" handle included: a configured instance
// is dragged onto a view to apply it, onto the Library or the Desktop to keep it.

import { useEffect, useMemo, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import type { ProcessMeta } from '../api/types';
import { client } from '../api/client';
import {
  pythonSourceFor,
  setDragImage,
  setDragPayload,
  type DragPayload,
} from '../dnd/dnd';
import { docTarget } from '../center/docTarget';
import { noteProcessFocus } from './focused';
import { pushToast } from '../notifications/store';
import { newScript } from '../scripts/scripts';
import { seededValues, takeSeed } from '../shell/layoutClient';
import { activeView, processes, viewById } from '../state/store';
import { ParameterGrid } from './ParameterGrid';
import { cancelJob, jobFor, runProcess } from './jobs';
import { acquireRtp, ownsRtp, releaseRtp, requestRtp } from './rtp';
import { customPanelFor } from './customPanels';

interface Props {
  processId: string;
  onClose: () => void;
}

function defaultsOf(meta: ProcessMeta): Record<string, unknown> {
  return Object.fromEntries(meta.parameters.map((p) => [p.id, p.default]));
}

export function ProcessPanel({ processId, onClose }: Props) {
  const meta = processes.value.find((p) => p.process_id === processId);
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    meta ? defaultsOf(meta) : {},
  );
  const job = jobFor(processId);
  const view = activeView.value;
  const initial = useMemo(() => (meta ? defaultsOf(meta) : {}), [meta]);
  // "Track view" — checked by default: the preview shows what is being looked at. Unchecking
  // pins the view of the moment, so as to compare a setting while navigating elsewhere.
  const [track, setTrack] = useState(true);
  const [pinned, setPinned] = useState<string | null>(null);
  const target = track ? view : (pinned ? viewById(pinned)?.view ?? null : null);
  // The values by reference: the tracking effect must not resubscribe on every keystroke,
  // yet it re-requests the preview with the CURRENT values — a closure would freeze them.
  const valuesRef = useRef(values);
  valuesRef.current = values;

  // Pre-filled opening — double-click on a recipe step, or
  // `app.layout.open_process('GaussianConvolution', {'sigma': 3.5})` in the console. An
  // effect rather than an initial state: the panel may **already** be open when the call
  // arrives, in which case it does not remount and would never see the values.
  useEffect(() => {
    if (!meta || !seededValues.value[processId]) return;
    const seed = takeSeed(processId);
    if (seed) setValues({ ...defaultsOf(meta), ...seed });
  }, [seededValues.value[processId], meta]);

  // Follows the target view: change of active view (Track view) and change of its PIXELS
  // (`pixel_gen` moves when a process is applied to it). Without it, the preview stayed
  // frozen on the previous image without saying so. `values` is out of the dependencies on
  // purpose: parameter changes go through `update`, which is already debounced.
  useEffect(() => {
    if (!ownsRtp(processId) || !target) return;
    requestRtp(processId, valuesRef.current, target.id);
  }, [processId, ownsRtp(processId), target?.id, target?.pixel_gen]);

  if (!meta) {
    return (
      <p style={{ padding: '8px 12px', color: 'var(--vscode-descriptionForeground)' }}>
        {m.process_unknown({ id: processId })}
      </p>
    );
  }

  const previewing = ownsRtp(processId);
  const Custom = customPanelFor(processId);

  // Every parameter change re-requests a preview (debounced on the client side).
  const update = (next: Record<string, unknown>) => {
    setValues(next);
    if (previewing && target) requestRtp(processId, next, target.id);
  };

  const togglePreview = (on: boolean) => {
    if (on) acquireRtp(processId);
    else releaseRtp(processId);
    // The initial request is left to the tracking effect: doing it here as well would send
    // two, and the debounce would not fold them (one leaves before it arms).
  };

  const apply = () => {
    // RPC refusal (invalid form, no target view): a local toast — an *execution* failure, on
    // the other hand, arrives through the notification centre (job.error on the server side).
    runProcess(processId, values).catch((e: unknown) => {
      pushToast('error', e instanceof Error ? e.message : String(e), processId);
    });
  };

  // The tab is asked for the page of THIS process, not for the index: the button carries a
  // book and the tooltip promises "Documentation", so landing on a table of contents was a
  // small betrayal — and `docTarget`, the mechanism that makes it exact, already existed for
  // the assistant.
  const showDoc = () => {
    docTarget.value = processId;
    void client.call('layout.show', { panel: 'doc' }).catch(() => undefined);
  };

  return (
    <div
      style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
      onPointerDownCapture={() => noteProcessFocus(processId)}
    >
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 12px' }}>
        {Custom && <Custom processId={processId} values={values} onChange={update} />}
        {meta.parameters.length === 0 && (
          <p style={{ color: 'var(--vscode-descriptionForeground)', fontSize: '12px' }}>
            {m.process_no_parameters()}
          </p>
        )}
        <ParameterGrid parameters={meta.parameters} values={values} onChange={update} />
      </div>

      {job && (
        // Long processes (integration, measurements, registration, denoising) report their
        // progress; the others run in one pass and leave `fraction` at `null`. The full,
        // dimmed bar then says "it is running" without claiming to know more.
        <>
          <div style={{ height: '2px', background: 'var(--vscode-input-border)' }}>
            <div
              style={{
                height: '100%',
                width: job.fraction === null ? '100%' : `${job.fraction * 100}%`,
                background: 'var(--vscode-progressBar-background)',
                opacity: job.fraction === null ? 0.5 : 1,
                transition: 'width 120ms linear',
              }}
            />
          </div>
          {job.message && (
            <div
              style={{
                fontSize: '11px',
                padding: '2px 8px',
                color: 'var(--vscode-descriptionForeground)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {job.message}
            </div>
          )}
        </>
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '6px 10px',
          borderTop: '1px solid var(--vscode-panel-border)',
        }}
      >
        <span
          draggable
          title={m.process_new_instance()}
          style={{ cursor: 'grab', fontSize: '14px' }}
          onDragStart={(event) => {
            const transfer = (event as DragEvent).dataTransfer;
            if (!transfer) return;
            const payload: DragPayload = {
              kind: 'instance',
              processes: [{ process_id: processId, values }],
              isGlobal: meta.is_global,
            };
            setDragPayload(transfer, payload, pythonSourceFor(payload));
            setDragImage(transfer, processId);
          }}
        >
          ⠿
        </span>
        <button
          onClick={apply}
          disabled={job !== null}
          title={
            meta.is_global
              ? m.process_execute_tip()
              : m.process_apply_to_tip({ target: view?.id ?? m.process_active_view() })
          }
          style={{
            background: 'var(--vscode-button-background)',
            color: 'var(--vscode-button-foreground)',
            border: 'none',
            borderRadius: '2px',
            padding: '4px 12px',
            font: '12px var(--retina-font-ui)',
            cursor: job ? 'default' : 'pointer',
            opacity: job ? 0.5 : 1,
          }}
        >
          {meta.is_global ? m.process_execute() : m.prompt_apply()}
        </button>
        {/* "Instance source code" — a button that belongs on *every* process interface. Here
            `to_python_source` had existed since day one without any interface calling it: the
            form could do everything, except state its own code. The result opens in a script
            tab, hence editable and runnable. */}
        <button
          class="btn"
          title={m.process_source_tip()}
          onClick={() => {
            void client
              .call<string>('app.source', { process_id: processId, values })
              .then((source) => newScript(`${source}\n`))
              .catch((error: unknown) => pushToast('error', String(error), processId));
          }}
          style={{ padding: '4px 8px' }}
        >
          <i class="codicon codicon-file-code" aria-hidden="true" />
        </button>
        {job && (
          <button
            onClick={() => cancelJob(job.id)}
            title={m.process_cancel_tip()}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--vscode-errorForeground)',
              cursor: 'pointer',
              fontSize: '14px',
            }}
          >
            <i class="codicon codicon-debug-stop" aria-hidden="true" />
          </button>
        )}
        <button
          onClick={() => setValues(initial)}
          style={{
            background: 'var(--vscode-button-secondaryBackground)',
            color: 'var(--vscode-button-secondaryForeground)',
            border: 'none',
            borderRadius: '2px',
            padding: '4px 10px',
            font: '12px var(--retina-font-ui)',
            cursor: 'pointer',
          }}
        >
          {m.process_reset()}
        </button>
        {meta.supports_realtime && !meta.is_global && (
          <label
            style={{ display: 'flex', gap: '4px', alignItems: 'center', fontSize: '12px' }}
            title={m.process_preview_tip()}
          >
            <input
              type="checkbox"
              checked={previewing}
              onChange={(event) => togglePreview((event.target as HTMLInputElement).checked)}
            />
            {m.process_preview()}
          </label>
        )}
        {previewing && (
          <label
            style={{ display: 'flex', gap: '4px', alignItems: 'center', fontSize: '12px' }}
            title={m.process_track_view_tip()}
          >
            <input
              type="checkbox"
              checked={track}
              onChange={(event) => {
                const on = (event.target as HTMLInputElement).checked;
                setTrack(on);
                setPinned(on ? null : (target?.id ?? null));
              }}
            />
            {m.process_track_view()}
          </label>
        )}
        <span style={{ flex: 1 }} />
        {meta.has_doc && (
          <button
            onClick={showDoc}
            title={m.process_doc_tip()}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--vscode-foreground)',
              cursor: 'pointer',
              fontSize: '14px',
            }}
          >
            <i class="codicon codicon-book" aria-hidden="true" />
          </button>
        )}
        <button
          onClick={() => {
            releaseRtp(processId);
            onClose();
          }}
          title={m.prompt_close()}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--vscode-foreground)',
            cursor: 'pointer',
            fontSize: '14px',
          }}
        >
          <i class="codicon codicon-close" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
