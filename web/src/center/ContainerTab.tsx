// Recipe editor — web port of the `container_panel` of the removed Qt shell.
//
// A recipe is an **ordered** list of configured instances: it is the ProcessContainer, and the
// project's reproducibility primitive. The order is the meaning of the object — stretch then
// denoise is not denoise then stretch — hence the care put into reordering and the refusal, on
// the server side, to scatter execution into concurrent jobs (`process.run_container`).
//
// What the Qt panel had and this reproduces identically: reorderable list, external drop of an
// instance at the end of the list, double-click on a step to reopen its **pre-filled** form,
// execution on the active view, saving to the library. What it did not have: the per-step run
// button, which the per-view history makes undoable one at a time.

import { useState } from 'preact/hooks';

import { client } from '../api/client';
import { m } from '../paraglide/messages';
import { plural } from '../ui/plural';
import {
  MIME_CONTAINER,
  MIME_PROCESS,
  readDragPayload,
  type ProcessPayload,
} from '../dnd/dnd';
import {
  containerById,
  insertStep,
  isEnabled,
  moveStep,
  openContainers,
  removeStep,
  saveContainer,
  setStepEnabled,
  setStepMask,
  setSteps,
  type RecipeStep,
} from '../pipeline/containerEdit';
import { runContainer, runProcess } from '../processes/jobs';
import { newScript } from '../scripts/scripts';
import { RECIPE_FILTERS, askPath } from '../shell/native';
import { TablerIcon } from '../shell/TablerIcon';
import { processes, windows } from '../state/store';
import { promptText } from '../ui/prompts';

/** Summary of a step: `GaussianConvolution(sigma=3.5)`, like the domain's `repr`. */
function describe(step: RecipeStep): string {
  const args = Object.entries(step.values)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(', ');
  return `${step.process_id}(${args})`;
}

export function ContainerTab({ id }: { id: string }) {
  const doc = openContainers.value.find((entry) => entry.id === id);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [dropAt, setDropAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Any open view can serve as a mask — that is also what `app.set_mask` accepts.
  const maskCandidates = windows.value.flatMap((win) => win.views.map((view) => view.id));

  if (!doc) return null;
  const steps = doc.steps;

  const fail = (exception: unknown) =>
    setError(exception instanceof Error ? exception.message : String(exception));

  const save = () => {
    void promptText(m.container_name_prompt(), doc.name ?? doc.title).then((name) => {
      if (name) void saveContainer(id, name).catch(fail);
    });
  };

  const runAll = () => {
    setError(null);
    void runContainer(steps, undefined, doc.name ?? doc.title).catch(fail);
  };

  const runOne = (step: ProcessPayload) => {
    setError(null);
    void runProcess(step.process_id, step.values).catch(fail);
  };

  /** Reopen the process form, filled with the step's values. */
  const edit = (step: ProcessPayload) => {
    void client
      .call('layout.open_process', { process_id: step.process_id, values: step.values })
      .catch(fail);
  };

  const onDropOnRow = (event: DragEvent, index: number) => {
    event.preventDefault();
    event.stopPropagation();
    setDropAt(null);
    if (dragFrom !== null) {
      // Internal reordering. `index` is the wanted final position: that is `moveStep`'s
      // convention, and moving a step down one notch depends on it.
      setSteps(id, moveStep(steps, dragFrom, index));
      setDragFrom(null);
      return;
    }
    const payload = event.dataTransfer && readDragPayload(event.dataTransfer);
    if (payload) {
      setSteps(id, payload.processes.reduce((acc, p) => insertStep(acc, p, index), [...steps]));
    }
  };

  const onDropOnList = (event: DragEvent) => {
    event.preventDefault();
    setDropAt(null);
    if (dragFrom !== null) {
      setSteps(id, moveStep(steps, dragFrom, steps.length - 1));
      setDragFrom(null);
      return;
    }
    const payload = event.dataTransfer && readDragPayload(event.dataTransfer);
    if (payload) setSteps(id, [...steps, ...payload.processes]);
  };

  const accepts = (event: DragEvent) =>
    dragFrom !== null ||
    !!event.dataTransfer?.types.some((t) => t === MIME_PROCESS || t === MIME_CONTAINER);

  return (
    <div
      class="container-tab"
      style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '6px 10px',
          borderBottom: '1px solid var(--vscode-panel-border)',
        }}
      >
        <button
          class="btn btn-primary"
          onClick={runAll}
          disabled={steps.length === 0}
          title={m.container_run_all_title()}
        >
          <i class="codicon codicon-play" aria-hidden="true" /> {m.container_run_all()}
        </button>
        <button class="btn" onClick={save} disabled={steps.length === 0}>
          <i class="codicon codicon-save" aria-hidden="true" /> {m.container_save()}
        </button>
        {/* A recipe must be able to leave the application: as a script, to read it and edit
            it; as XML, to exchange it. */}
        <button
          class="btn"
          disabled={steps.length === 0}
          title={m.container_to_script_title()}
          onClick={() => {
            void client
              .call<string>('process.container_source', { processes: steps })
              .then((source) => newScript(`${source}\n`))
              .catch(fail);
          }}
        >
          <i class="codicon codicon-file-code" aria-hidden="true" /> {m.container_to_script()}
        </button>
        <button
          class="btn"
          disabled={steps.length === 0}
          title={m.container_export_title()}
          onClick={() => {
            void (async () => {
              const xml = await client.call<string>('process.container_xml', { processes: steps });
              const chosen = await askPath({
                title: m.container_export_dialog(),
                save: true,
                filters: RECIPE_FILTERS,
                filename: `${doc.name ?? doc.title}.xml`,
              });
              if (chosen?.[0]) await client.call('fs.write_text', { path: chosen[0], text: xml });
            })().catch(fail);
          }}
        >
          {m.container_export()}
        </button>
        <button
          class="btn"
          title={m.container_load_title()}
          onClick={() => {
            void (async () => {
              const chosen = await askPath({
                title: m.container_load_dialog(),
                filters: RECIPE_FILTERS,
              });
              if (!chosen?.[0]) return;
              const { text } = await client.call<{ text: string }>('fs.read_text', {
                path: chosen[0],
              });
              setSteps(id, await client.call<RecipeStep[]>('process.container_from_xml', { text }));
            })().catch(fail);
          }}
        >
          {m.container_load()}
        </button>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: '11px', color: 'var(--vscode-descriptionForeground)' }}>
          {plural(
            steps.length,
            m.container_step({ count: steps.length }),
            m.container_steps({ count: steps.length }),
          )}
          {doc.dirty ? ` — ${m.container_unsaved()}` : ''}
        </span>
      </div>

      {error && (
        <p
          style={{
            margin: 0,
            padding: '6px 10px',
            fontSize: '12px',
            color: 'var(--vscode-errorForeground)',
          }}
        >
          {error}
        </p>
      )}

      <div
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '6px 0' }}
        onDragOver={(event: DragEvent) => {
          if (!accepts(event)) return;
          event.preventDefault();
          event.dataTransfer!.dropEffect = dragFrom !== null ? 'move' : 'copy';
        }}
        onDrop={onDropOnList}
      >
        {steps.length === 0 && (
          <p
            style={{
              color: 'var(--vscode-descriptionForeground)',
              fontSize: '12px',
              padding: '8px 12px',
              margin: 0,
            }}
          >
            {m.container_empty()}
          </p>
        )}

        {steps.map((step, index) => (
          <div
            key={`${step.process_id}-${index}`}
            class="tree-row"
            draggable
            aria-label={describe(step)}
            style={{
              borderTop:
                dropAt === index ? '2px solid var(--retina-drop-legal)' : '2px solid transparent',
            }}
            onDragStart={(event: DragEvent) => {
              setDragFrom(index);
              event.dataTransfer!.effectAllowed = 'move';
              // `text/plain` only: setting a process MIME would make the viewport accept the
              // drag, and it would apply the step instead of moving it.
              event.dataTransfer!.setData('text/plain', describe(step));
            }}
            onDragEnd={() => {
              setDragFrom(null);
              setDropAt(null);
            }}
            onDragOver={(event: DragEvent) => {
              if (!accepts(event)) return;
              event.preventDefault();
              event.stopPropagation();
              setDropAt(index);
            }}
            onDragLeave={() => setDropAt((current) => (current === index ? null : current))}
            onDrop={(event: DragEvent) => onDropOnRow(event, index)}
            onDblClick={() => edit(step)}
            title={m.container_step_dblclick()}
          >
            <input
              type="checkbox"
              checked={isEnabled(step)}
              title={m.container_step_enabled_title()}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) =>
                setSteps(
                  id,
                  setStepEnabled(steps, index, (event.currentTarget as HTMLInputElement).checked),
                )
              }
            />
            <span
              style={{
                width: '2em',
                textAlign: 'right',
                color: 'var(--vscode-descriptionForeground)',
                fontSize: '11px',
              }}
            >
              {index + 1}
            </span>
            <TablerIcon
              name={processes.value.find((p) => p.process_id === step.process_id)?.icon ?? 'wand'}
            />
            <span
              style={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                // A disabled step stays readable but stops blending in with the others: that
                // is the whole point of keeping it in the list.
                opacity: isEnabled(step) ? 1 : 0.45,
                textDecoration: isEnabled(step) ? 'none' : 'line-through',
              }}
            >
              {describe(step)}
            </span>
            <span style={{ flex: 1 }} />
            <select
              value={step.mask ?? ''}
              title={m.container_step_mask_title()}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) =>
                setSteps(
                  id,
                  setStepMask(
                    steps,
                    index,
                    (event.currentTarget as HTMLSelectElement).value || null,
                    step.mask_inverted ?? false,
                  ),
                )
              }
              style={{ maxWidth: '9em', fontSize: '11px' }}
            >
              <option value="">{m.container_no_mask()}</option>
              {maskCandidates.map((viewId) => (
                <option key={viewId} value={viewId}>
                  {viewId}
                </option>
              ))}
            </select>
            {step.mask && (
              <button
                class="btn"
                title={step.mask_inverted ? m.container_mask_inverted() : m.container_mask_normal()}
                onClick={(event) => {
                  event.stopPropagation();
                  setSteps(id, setStepMask(steps, index, step.mask ?? null, !step.mask_inverted));
                }}
                style={{ padding: '0 6px' }}
              >
                <i
                  class={`codicon codicon-${step.mask_inverted ? 'circle-slash' : 'circle-outline'}`}
                  aria-hidden="true"
                />
              </button>
            )}
            <button
              class="btn"
              title={m.container_run_step_title()}
              onClick={(event) => {
                event.stopPropagation();
                runOne(step);
              }}
              style={{ padding: '0 6px' }}
            >
              <i class="codicon codicon-play" aria-hidden="true" />
            </button>
            <button
              class="btn"
              title={m.container_remove_step()}
              onClick={(event) => {
                event.stopPropagation();
                setSteps(id, removeStep(steps, index));
              }}
              style={{ padding: '0 6px' }}
            >
              <i class="codicon codicon-trash" aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Tab title — the dot marks a recipe modified but not saved. */
export function titleForContainer(id: string): string {
  const doc = containerById(id);
  if (!doc) return id;
  return `${doc.dirty ? '● ' : ''}${doc.title}`;
}
