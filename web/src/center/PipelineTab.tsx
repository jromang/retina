// Centre tab "Preprocessing" — the automated preprocessing wizard.
//
// One more client of the API: it chains `pipeline.scan`, `pipeline.plan` and `pipeline.run`,
// and it is the server that echoes the equivalent Python. The walkthrough comes in four
// stages — pick a folder, read back what was detected, read back what is going to be done,
// launch — because a preprocessing run that starts on a bad grouping costs hours.
//
// The logic is in `../pipeline/model`: this file only renders it.

import { Fragment } from 'preact';
import { useEffect, useState } from 'preact/hooks';

import {
  type GroupRow,
  type Kind,
  KINDS,
  buildPlan,
  busy,
  calibrationSummary,
  cancel,
  diskShort,
  error,
  folder,
  formatBytes,
  formatDuration,
  groupRows,
  groupSizes,
  groupWarnings,
  inventory,
  job,
  loadPresets,
  openResult,
  plan,
  preset,
  presets,
  reclassify,
  report,
  reset,
  running,
  scan,
  selectedStep,
  setExcluded,
  setPreset,
  start,
  totalIntegration,
  unknownFrames,
} from '../pipeline/model';
import { client } from '../api/client';
import { m } from '../paraglide/messages';
import { plural } from '../ui/plural';
import { askPath } from '../shell/native';
import { PlanStepEditor } from './PlanStepEditor';

const KIND_LABEL: Record<string, string> = {
  light: m.pipeline_kind_light(),
  dark: m.pipeline_kind_dark(),
  flat: m.pipeline_kind_flat(),
  bias: m.pipeline_kind_bias(),
  unknown: m.pipeline_kind_unknown(),
};

/** Frame-kind selector — the correction is made in place, without a context menu. */
function KindSelect({
  value,
  onPick,
  label,
}: {
  value: string;
  onPick: (kind: Kind) => void;
  label: string;
}) {
  return (
    <select
      value={value}
      aria-label={label}
      disabled={running.value || busy.value}
      onChange={(e) => onPick((e.target as HTMLSelectElement).value as Kind)}
      style={{ font: 'inherit', fontSize: '12px', padding: '0 2px' }}
    >
      {value === 'unknown' && <option value="unknown">{m.pipeline_kind_unclassified()}</option>}
      {KINDS.map((k) => (
        <option key={k} value={k}>
          {KIND_LABEL[k]}
        </option>
      ))}
    </select>
  );
}

const CELL = { padding: '3px 8px' };

/**
 * What the group will receive at calibration — **spelled out**.
 *
 * A grid of 16 px icons without a legend would make "no master found" and "master forbidden
 * by the user" indistinguishable. Text takes more room and reads without any learning.
 */
function Calibration({ row }: { row: GroupRow }) {
  const resume = calibrationSummary(row);
  if (!resume) return <>—</>;
  return (
    <>
      {resume.has || (resume.missing.length ? '' : m.pipeline_nothing_to_subtract())}
      {resume.missing.length > 0 && (
        <span style={{ color: 'var(--vscode-editorWarning-foreground)' }}>
          {resume.has ? ' · ' : ''}
          {m.pipeline_without({ what: resume.missing.join(m.pipeline_missing_join()) })}
        </span>
      )}
    </>
  );
}

/** One link of the chain: the group going in, or the master applied to it. */
function Node({
  title,
  detail,
  strong,
}: {
  title: string;
  detail?: string;
  strong?: boolean;
}) {
  return (
    <span
      style={{
        border: '1px solid var(--vscode-input-border)',
        borderRadius: '3px',
        padding: '3px 7px',
        whiteSpace: 'nowrap',
        fontWeight: strong ? 600 : 400,
      }}
    >
      {title}
      {detail && (
        <span style={{ color: 'var(--vscode-descriptionForeground)' }}> · {detail}</span>
      )}
    </span>
  );
}

/**
 * The group's calibration chain, drawn.
 *
 * The operations and their order come from the domain (`CalibrationMatch.chain`): it is
 * `ImageCalibration`'s formula with the masters actually selected, not a reconstruction. It is
 * drawn under the group's row rather than behind a button: what one wants to check at a glance
 * must not require a gesture.
 */
function CalibrationChain({ row }: { row: GroupRow }) {
  const etapes = row.calibration?.chain ?? [];
  const tailles = groupSizes.value;
  if (!etapes.length) {
    return (
      <p style={{ margin: 0, color: 'var(--vscode-editorWarning-foreground)' }}>
        {m.pipeline_no_master()}
      </p>
    );
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px' }}>
      <Node title={`${row.count} × ${KIND_LABEL[row.kind] ?? row.kind}`} strong />
      {etapes.map((etape) => (
        <Fragment key={`${etape.role}·${etape.master}`}>
          <span style={{ color: 'var(--vscode-descriptionForeground)' }}>
            {etape.op === 'divide' ? '÷' : '−'}
          </span>
          <Node
            title={etape.master}
            detail={[
              tailles[etape.master]
                ? m.pipeline_frames_count({ count: tailles[etape.master]! })
                : undefined,
              etape.scale === 1 ? undefined : `×${etape.scale.toFixed(2)}`,
              // The dark current frame is the only intermediate made along the way: hiding it
              // would suggest the master dark is scaled as is, bias included.
              etape.derived ? m.pipeline_dark_current({ bias: etape.derived }) : undefined,
            ]
              .filter(Boolean)
              .join(' · ')}
          />
        </Fragment>
      ))}
      <span style={{ color: 'var(--vscode-descriptionForeground)' }}>→</span>
      <Node title={m.pipeline_calibrated()} strong />
    </div>
  );
}

function GroupRowView({
  row,
  open,
  onToggle,
}: {
  row: GroupRow;
  open: boolean;
  onToggle: () => void;
}) {
  const efface = row.excluded ? 0.45 : 1;
  const calibrable = row.calibration !== null;
  return (
    <>
    <tr style={{ borderTop: '1px solid var(--vscode-input-border)' }}>
      <td style={{ padding: '3px 6px 3px 0' }}>
        <input
          type="checkbox"
          checked={!row.excluded}
          disabled={running.value || busy.value}
          title={row.excluded ? m.pipeline_group_include() : m.pipeline_group_exclude()}
          aria-label={m.pipeline_include_kind({ kind: KIND_LABEL[row.kind] ?? row.kind })}
          onChange={(e) => {
            void setExcluded(row.paths, !(e.target as HTMLInputElement).checked);
          }}
        />
      </td>
      <td style={{ ...CELL, paddingLeft: 0 }}>
        <KindSelect
          value={row.kind}
          label={m.pipeline_group_kind_label({ key: row.key })}
          onPick={(kind) => void reclassify(row.paths, kind)}
        />
        {row.guessed && (
          // A classification deduced from the file name is more fragile than a header: saying
          // so is better than hiding it. Correcting the kind makes the mark disappear.
          <span
            title={m.pipeline_kind_guessed()}
            style={{ marginLeft: '4px', opacity: 0.7 }}
          >
            ?
          </span>
        )}
      </td>
      <td style={{ ...CELL, opacity: efface }}>{row.filter ?? '—'}</td>
      <td style={{ ...CELL, opacity: efface }}>
        {row.exposure === null ? '—' : `${row.exposure} s`}
      </td>
      <td style={{ ...CELL, opacity: efface }}>{row.binning}</td>
      <td style={{ ...CELL, opacity: efface }}>
        {row.temperature === null ? '—' : `${row.temperature} °C`}
      </td>
      <td
        style={{
          ...CELL,
          textAlign: 'right',
          opacity: efface,
          textDecoration: row.excluded ? 'line-through' : 'none',
        }}
      >
        {row.count}
      </td>
      <td style={{ ...CELL, opacity: efface }}>
        {calibrable ? (
          <button
            onClick={onToggle}
            aria-expanded={open}
            aria-label={m.pipeline_chain_of({ key: row.key })}
            style={{
              font: 'inherit',
              background: 'none',
              border: 'none',
              padding: 0,
              color: 'inherit',
              cursor: 'pointer',
              textAlign: 'left',
            }}
          >
            <span style={{ color: 'var(--vscode-descriptionForeground)' }}>
              {open ? '▾ ' : '▸ '}
            </span>
            <Calibration row={row} />
          </button>
        ) : (
          <Calibration row={row} />
        )}
      </td>
    </tr>
    {open && (
      <tr>
        <td colSpan={8} style={{ padding: '2px 8px 10px 26px' }}>
          <CalibrationChain row={row} />
        </td>
      </tr>
    )}
    </>
  );
}

/**
 * What the selection actually kept — and the door to the screen that lets one revisit it.
 *
 * The "5 · What you will get" section announces an **upper bound**: the plan is built before
 * any measurement, so it counts the exposures the selector will drop. Once the run is over the
 * real figure is known, and that is the one worth reading.
 */
function SelectionSummary() {
  const produits = report.value?.products ?? [];
  const trie = produits.some((p) => p.rejected > 0);
  if (!produits.length) return null;
  return (
    <div style={{ marginTop: '8px', fontSize: '12px' }}>
      <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
        {produits.map((produit) => (
          <li key={produit.key} style={{ padding: '1px 0' }}>
            <span style={{ color: 'var(--vscode-descriptionForeground)' }}>{produit.key}</span>{' '}
            —{' '}
            {plural(
              produit.frames,
              m.pipeline_product_kept_one({
                kept: produit.frames,
                measured: produit.measured || produit.frames,
                duration: formatDuration(produit.integration),
              }),
              m.pipeline_product_kept_many({
                kept: produit.frames,
                measured: produit.measured || produit.frames,
                duration: formatDuration(produit.integration),
              }),
            )}
            {produit.rejected > 0 &&
              plural(
                produit.rejected,
                m.pipeline_product_rejected_one({ count: produit.rejected }),
                m.pipeline_product_rejected_many({ count: produit.rejected }),
              )}
          </li>
        ))}
      </ul>
      <button
        className="btn"
        style={{ marginTop: '6px' }}
        title={m.pipeline_selection_button_title()}
        onClick={() => {
          void client.call('layout.show', { panel: 'selector' }).catch(() => undefined);
        }}
      >
        {trie ? m.pipeline_review_selection() : m.pipeline_sort_frames()}
      </button>
    </div>
  );
}

function Section({ title, children }: { title: string; children: preact.ComponentChildren }) {
  return (
    <section style={{ marginBottom: '18px' }}>
      <h3
        style={{
          font: 'inherit',
          fontWeight: 600,
          textTransform: 'uppercase',
          fontSize: '11px',
          letterSpacing: '0.06em',
          color: 'var(--vscode-descriptionForeground)',
          margin: '0 0 6px',
        }}
      >
        {title}
      </h3>
      {children}
    </section>
  );
}

function GroupTable() {
  const rows = groupRows.value;
  // Which row shows its chain — purely a display state, it has no business in the model nor
  // any reason to cross the network.
  const [ouvert, setOuvert] = useState<string | null>(null);
  if (!rows.length) return null;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '12px' }}>
        <thead>
          <tr style={{ textAlign: 'left', color: 'var(--vscode-descriptionForeground)' }}>
            <th style={{ padding: '3px 6px 3px 0' }} title={m.pipeline_include_header()} />
            <th style={{ padding: '3px 8px 3px 0' }}>{m.pipeline_col_type()}</th>
            <th style={CELL}>{m.pipeline_col_filter()}</th>
            <th style={CELL}>{m.pipeline_col_exposure()}</th>
            <th style={CELL}>{m.pipeline_col_binning()}</th>
            <th style={CELL}>{m.pipeline_col_temp()}</th>
            <th style={{ ...CELL, textAlign: 'right' }}>{m.pipeline_col_frames()}</th>
            <th style={CELL}>{m.pipeline_col_calibration()}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <GroupRowView
              key={row.key}
              row={row}
              open={ouvert === row.key}
              onToggle={() => setOuvert(ouvert === row.key ? null : row.key)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The matching remarks, group by group.
 *
 * They are short and few — most groups have none — so they fit under the table, visible
 * without a gesture rather than behind a click or in a diagnostics modal.
 */
function GroupWarnings() {
  const items = groupWarnings.value;
  if (!items.length) return null;
  return (
    <ul style={{ margin: '6px 0 0', paddingLeft: '18px', fontSize: '12px' }}>
      {items.map(({ key, note }) => (
        <li key={`${key}·${note}`} style={{ color: 'var(--vscode-editorWarning-foreground)' }}>
          <span style={{ color: 'var(--vscode-descriptionForeground)' }}>{key}</span> — {note}
        </li>
      ))}
    </ul>
  );
}

/** The files we could not classify — and what is needed to do it by hand. */
function UnknownFrames() {
  const frames = unknownFrames.value;
  if (!frames.length) return null;
  return (
    <div style={{ marginTop: '8px' }}>
      <p style={{ color: 'var(--vscode-editorWarning-foreground)', fontSize: '12px', margin: 0 }}>
        {plural(
          frames.length,
          m.pipeline_unknown_frame_one({ count: frames.length }),
          m.pipeline_unknown_frame_many({ count: frames.length }),
        )}
      </p>
      <ul style={{ margin: '4px 0 0', padding: 0, listStyle: 'none', fontSize: '12px' }}>
        {frames.map((frame) => (
          <li
            key={frame.path}
            style={{ display: 'flex', gap: '8px', alignItems: 'center', padding: '1px 0' }}
          >
            <KindSelect
              value="unknown"
              label={m.pipeline_kind_of({ path: frame.path })}
              onPick={(kind) => void reclassify([frame.path], kind)}
            />
            <span
              title={frame.path}
              style={{ color: 'var(--vscode-descriptionForeground)' }}
            >
              {frame.path.split(/[/\\]/).pop()}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * What the plan is going to yield, and what it is going to cost.
 *
 * The **cumulative exposure** is the figure that decides whether the night was worth it, and
 * no other screen gives it. Disk space, for its part, is checked before launching, not after
 * three hours: a ×2 drizzle over three hundred exposures demands four hundred gigabytes.
 */
function Products() {
  const info = plan.value;
  if (!info?.products.length) return null;
  const disque = info.disk;
  return (
    <>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '12px' }}>
          <thead>
            <tr style={{ textAlign: 'left', color: 'var(--vscode-descriptionForeground)' }}>
              <th style={{ padding: '3px 8px 3px 0' }}>{m.pipeline_col_filter()}</th>
              <th style={{ ...CELL, textAlign: 'right' }}>{m.pipeline_col_exposures()}</th>
              <th style={{ ...CELL, textAlign: 'right' }}>{m.pipeline_col_unit()}</th>
              <th style={{ ...CELL, textAlign: 'right' }}>{m.pipeline_col_integration()}</th>
              <th style={CELL}>{m.pipeline_col_file()}</th>
            </tr>
          </thead>
          <tbody>
            {info.products.map((produit) => (
              <tr key={produit.key} style={{ borderTop: '1px solid var(--vscode-input-border)' }}>
                <td style={{ padding: '3px 8px 3px 0' }}>{produit.filter ?? '—'}</td>
                <td style={{ ...CELL, textAlign: 'right' }}>{produit.frames}</td>
                <td style={{ ...CELL, textAlign: 'right' }}>
                  {produit.exposure === null ? '—' : `${produit.exposure} s`}
                </td>
                <td style={{ ...CELL, textAlign: 'right', fontWeight: 600 }}>
                  {formatDuration(produit.integration)}
                </td>
                <td style={{ ...CELL, color: 'var(--vscode-descriptionForeground)' }}>
                  {produit.path.split(/[/\\]/).pop()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: '12px', margin: '8px 0 0' }}>
        {info.products.length > 1 && (
          <>
            {m.pipeline_total_integration()} <b>{formatDuration(totalIntegration.value)}</b> ·{' '}
          </>
        )}
        {m.pipeline_to_write()} <b>{formatBytes(disque.total_bytes)}</b>
        {disque.free_bytes !== null && (
          <span style={{ color: diskShort.value ? 'var(--vscode-editorWarning-foreground)' : undefined }}>
            {' '}
            · {m.pipeline_free({ size: formatBytes(disque.free_bytes) })}
            {diskShort.value && ` — ${m.pipeline_insufficient()}`}
          </span>
        )}
      </p>
    </>
  );
}

function Notes({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul style={{ margin: '6px 0 0', paddingLeft: '18px', fontSize: '12px' }}>
      {items.map((note) => (
        <li key={note} style={{ color: 'var(--vscode-descriptionForeground)' }}>
          {note}
        </li>
      ))}
    </ul>
  );
}

export function PipelineTab() {
  useEffect(() => {
    if (!presets.value.length) void loadPresets();
  }, []);

  const choisirDossier = async () => {
    const chemins = await askPath({ title: m.pipeline_pick_folder(), folder: true });
    if (chemins?.[0]) void scan(chemins[0]);
  };

  const enCours = running.value;
  const avancement = job.value?.fraction;

  return (
    <div style={{ padding: '16px 20px', overflowY: 'auto', height: '100%', fontSize: '13px' }}>
      <h2 style={{ font: 'inherit', fontSize: '15px', fontWeight: 600, margin: '0 0 14px' }}>
        {m.panel_pipeline()}
      </h2>

      <Section title={m.pipeline_step1()}>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button className="btn" onClick={() => void choisirDossier()} disabled={enCours}>
            {m.pipeline_browse()}
          </button>
          <span style={{ opacity: folder.value ? 1 : 0.6 }}>
            {folder.value || m.pipeline_no_folder()}
          </span>
        </div>
      </Section>

      {inventory.value && (
        <Section title={m.pipeline_step2()}>
          <GroupTable />
          <GroupWarnings />
          <UnknownFrames />
        </Section>
      )}

      {inventory.value && (
        <Section title={m.pipeline_step3()}>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <select
              value={preset.value}
              disabled={enCours}
              onChange={(e) => {
                void setPreset((e.target as HTMLSelectElement).value);
              }}
            >
              {presets.value.map((p) => (
                <option key={p.name} value={p.name} title={p.hint}>
                  {p.label}
                </option>
              ))}
            </select>
            <button className="btn" onClick={() => void buildPlan()} disabled={enCours || busy.value}>
              {m.pipeline_build_plan()}
            </button>
          </div>
        </Section>
      )}

      {plan.value && (
        <Section title={m.pipeline_step4({ count: plan.value.steps.length })}>
          <Notes items={plan.value.notes} />
          <ol style={{ margin: '8px 0 0', paddingLeft: '22px', fontSize: '12px' }}>
            {plan.value.steps.map((step) => {
              const ouverte = selectedStep.value === step.id;
              return (
                <li key={step.id} style={{ padding: '1px 0' }}>
                  <button
                    onClick={() => {
                      selectedStep.value = ouverte ? null : step.id;
                    }}
                    title={m.pipeline_edit_step()}
                    aria-expanded={ouverte}
                    style={{
                      background: 'none',
                      border: 'none',
                      padding: 0,
                      font: 'inherit',
                      color: 'inherit',
                      cursor: 'pointer',
                      textAlign: 'left',
                    }}
                  >
                    <i
                      class={`codicon codicon-chevron-${ouverte ? 'down' : 'right'}`}
                      aria-hidden="true"
                    />{' '}
                    {step.label}
                    <span style={{ color: 'var(--vscode-descriptionForeground)' }}>
                      {' — '}
                      {step.processes.map((p) => p.process_id).join(' → ') || '—'}
                      {step.kind === 'per_frame'
                        ? ` · ${plural(
                            step.inputs.length,
                            m.pipeline_step_frame_one({ count: step.inputs.length }),
                            m.pipeline_step_frame_many({ count: step.inputs.length }),
                          )}`
                        : ''}
                      {step.hooks && Object.keys(step.hooks).length > 0
                        ? ` · ${m.pipeline_step_hooked()}`
                        : ''}
                    </span>
                  </button>
                  {ouverte && <PlanStepEditor step={step} />}
                </li>
              );
            })}
          </ol>
          <p style={{ fontSize: '12px', color: 'var(--vscode-descriptionForeground)' }}>
            {m.pipeline_outputs({ path: plan.value.output_dir })}
          </p>
        </Section>
      )}

      {plan.value && plan.value.products.length > 0 && (
        <Section title={m.pipeline_step5()}>
          <Products />
        </Section>
      )}

      {plan.value && (
        <Section title={m.pipeline_step6()}>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {!enCours && (
              <button className="btn" onClick={() => void start()} disabled={busy.value}>
                {m.pipeline_start()}
              </button>
            )}
            {enCours && (
              <button className="btn" onClick={cancel} title={m.pipeline_cancel_title()}>
                {m.pipeline_cancel()}
              </button>
            )}
            {report.value && (
              <button className="btn" onClick={reset}>
                {m.pipeline_new()}
              </button>
            )}
          </div>

          {enCours && (
            <div style={{ marginTop: '8px' }}>
              <div style={{ height: '3px', background: 'var(--vscode-input-border)' }}>
                <div
                  style={{
                    height: '100%',
                    width: avancement == null ? '100%' : `${avancement * 100}%`,
                    background: 'var(--vscode-progressBar-background)',
                    opacity: avancement == null ? 0.5 : 1,
                    transition: 'width 120ms linear',
                  }}
                />
              </div>
              <p style={{ fontSize: '12px', margin: '4px 0 0' }}>{job.value?.message ?? '…'}</p>
            </div>
          )}

          {report.value && (
            <div style={{ marginTop: '10px' }}>
              <p style={{ margin: 0 }}>
                {plural(
                  report.value.executed.length,
                  m.pipeline_report_run_one({ executed: report.value.executed.length }),
                  m.pipeline_report_run_many({ executed: report.value.executed.length }),
                )}
                {', '}
                {plural(
                  report.value.skipped.length,
                  m.pipeline_report_cached_one({ skipped: report.value.skipped.length }),
                  m.pipeline_report_cached_many({ skipped: report.value.skipped.length }),
                )}
              </p>
              <ul style={{ margin: '6px 0 0', padding: 0, listStyle: 'none', fontSize: '12px' }}>
                {report.value.results.map((chemin) => (
                  <li
                    key={chemin}
                    style={{ display: 'flex', gap: '8px', alignItems: 'center', padding: '1px 0' }}
                  >
                    {/* Twenty minutes of computation must not end with a round trip through
                        File → Open. An explicit button rather than opening by default: one
                        gesture, one `app.open(…)` echo, and there may be several images. */}
                    <button className="btn" onClick={() => openResult(chemin)}>
                      {m.pipeline_open()}
                    </button>
                    <span title={chemin}>{chemin.split(/[/\\]/).pop()}</span>
                  </li>
                ))}
              </ul>
              <SelectionSummary />
              <Notes items={report.value.notes} />
            </div>
          )}
        </Section>
      )}

      {error.value && (
        <p style={{ color: 'var(--vscode-errorForeground)', fontSize: '12px' }}>{error.value}</p>
      )}
    </div>
  );
}
