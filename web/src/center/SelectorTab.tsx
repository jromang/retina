// Centre tab "Frame selection" — sorting the exposures before stacking them.
//
// The one screen of the reference batch tool the analysis judged genuinely modern, and ours
// did not exist: the core already measured everything (FWHM, eccentricity from second-order
// moments, SNR, star count) and derived a weight from it, with no way to look at any of it.
//
// What is carried over: the group table, the frame table **sortable by column**, the criteria
// as free expressions, and "apply to every group". What is not carried over: its modal, which
// opens in the middle of the run and blocks it. Our measurements are on disk, so inspection
// happens **between two runs** — and relaunching recomputes only the integration.
//
// An exposure is judged by **looking at it**, not only by reading its FWHM: each row therefore
// opens its frame in the viewport (`app.open`, hence echoed). Without that gesture the screen
// would be only a spreadsheet — one would know an exposure scores 4.2 without being able to
// decide whether that is acceptable.
//
// The logic is in `../pipeline/selector`; this file only renders it.

import { Fragment } from 'preact';
import { useEffect } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { plural } from '../ui/plural';
import { formatDuration, plan } from '../pipeline/model';
import {
  type Criteria,
  type GroupSummary,
  type Measurement,
  activeGroup,
  basename,
  cellValue,
  criteriaError,
  currentCriteria,
  currentGroup,
  currentSummary,
  freezeRejections,
  groupKeys,
  hasMeasures,
  isManuallyRejected,
  loadMeasures,
  loading,
  measures,
  openFrame,
  referenceFrame,
  rows,
  selectedFrame,
  selectorError,
  setCriteria,
  setRejects,
  sortAscending,
  sortKey,
  sortedRows,
  toggleReject,
  visibleColumns,
  toggleSort,
} from '../pipeline/selector';
import { MetricGrid } from './MetricGrid';

const MUTED = 'var(--vscode-descriptionForeground)';
const RIGHT = { textAlign: 'right' } as const;

/** Labels of the rejection reasons — the internal jargon does not leave the domain. */
const REJECT_LABEL: Record<string, string> = {
  manual: m.selector_reject_manual(),
  expression: m.selector_reject_expression(),
  min_weight: m.selector_reject_min_weight(),
};

function Empty({ text }: { text: string }) {
  return <p style={{ color: MUTED, fontSize: '13px' }}>{text}</p>;
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
          color: MUTED,
          margin: '0 0 6px',
        }}
      >
        {title}
      </h3>
      {children}
    </section>
  );
}

/**
 * The group table — and, per row, the **real** cumulative exposure.
 *
 * This is the visual feedback that justifies sorting: watching the night melt from 4 h to
 * 3 h 20 by dropping six exposures. The plan can only announce an upper bound — it is built
 * before any measurement, and a rejected frame remains an input of the integration, it simply
 * weighs zero.
 */
function GroupTable() {
  const bilans = measures.value?.summary ?? [];
  if (!bilans.length) return null;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table class="data-table">
        <thead>
          <tr>
            <th>{m.selector_group_key()}</th>
            <th style={RIGHT}>{m.selector_group_measured()}</th>
            <th style={RIGHT}>{m.selector_group_kept()}</th>
            <th style={RIGHT}>{m.selector_group_rejected()}</th>
            <th style={RIGHT}>{m.selector_group_integration()}</th>
          </tr>
        </thead>
        <tbody>
          {bilans.map((bilan) => (
            <GroupLine key={bilan.key} bilan={bilan} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroupLine({ bilan }: { bilan: GroupSummary }) {
  const actif = bilan.key === currentGroup.value;
  const motifs = Object.entries(bilan.rejected_by)
    .map(([motif, n]) => `${n} ${REJECT_LABEL[motif] ?? motif}`)
    .join(', ');
  const choisir = () => {
    activeGroup.value = bilan.key;
  };
  return (
    <tr
      tabIndex={0}
      aria-selected={actif}
      onClick={choisir}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          choisir();
        }
      }}
      style={{ cursor: 'pointer' }}
    >
      <td>{bilan.key}</td>
      <td style={RIGHT}>{bilan.measured}</td>
      <td style={{ ...RIGHT, fontWeight: 600 }}>{bilan.frames}</td>
      <td style={RIGHT} title={motifs}>
        {bilan.rejected || '—'}
      </td>
      <td style={RIGHT}>{formatDuration(bilan.integration)}</td>
    </tr>
  );
}

/** The sortable header: clicking a column sorts, clicking again flips the direction. */
function HeaderCell({ id, label, hint }: { id: string; label: string; hint?: string }) {
  const actif = sortKey.value === id;
  const gauche = id === 'name' || id === 'rejected_by';
  return (
    <th
      tabIndex={0}
      role="columnheader"
      aria-sort={actif ? (sortAscending.value ? 'ascending' : 'descending') : 'none'}
      onClick={() => toggleSort(id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggleSort(id);
        }
      }}
      title={hint ?? m.selector_sort_by({ label })}
      style={{
        cursor: 'pointer',
        textAlign: gauche ? 'left' : 'right',
        color: actif ? 'var(--vscode-foreground)' : MUTED,
      }}
    >
      {label}
      {actif && <span aria-hidden="true">{sortAscending.value ? ' ▲' : ' ▼'}</span>}
    </th>
  );
}

function format(value: number | string, digits?: number): string {
  if (typeof value !== 'number') return value;
  return digits === undefined ? String(value) : value.toFixed(digits);
}

function FrameRow({ row, index }: { row: Measurement; index: number }) {
  const manuel = isManuallyRejected(row.frame);
  const choisie = selectedFrame.value === row.frame;
  const reference = referenceFrame.value === row.frame;
  // Zero stars is not a good score: it is a measurement that failed, and presenting it as a
  // perfect frame is precisely the trap `roundness_limit` fixed.
  const aveugle = row.stars === 0;
  return (
    <tr
      tabIndex={0}
      aria-selected={choisie}
      title={reference ? m.selector_reference_title() : undefined}
      onClick={() => {
        selectedFrame.value = row.frame;
      }}
      onDblClick={() => openFrame(row.frame)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          openFrame(row.frame);
        } else if (e.key === ' ') {
          e.preventDefault();
          void toggleReject(row.frame);
        }
      }}
      style={{ cursor: 'pointer', opacity: row.approved ? 1 : 0.55 }}
    >
      <td style={{ width: '1%' }}>
        <input
          type="checkbox"
          checked={!manuel}
          aria-label={m.selector_stack_frame({ name: basename(row.frame) })}
          title={manuel ? m.selector_reinstate() : m.selector_exclude()}
          onClick={(e) => e.stopPropagation()}
          onChange={() => void toggleReject(row.frame)}
        />
      </td>
      {visibleColumns.value.map((column) => {
        const valeur = cellValue(row, index, column.id);
        const alerte = column.id === 'stars' && aveugle;
        const gauche = column.id === 'name' || column.id === 'rejected_by';
        return (
          <td
            key={column.id}
            title={column.id === 'name' ? row.frame : undefined}
            style={{
              textAlign: gauche ? 'left' : 'right',
              fontVariantNumeric: 'tabular-nums',
              color: alerte ? 'var(--vscode-editorWarning-foreground)' : undefined,
            }}
          >
            {/* The reference fixes the geometry of the whole group: it is the last exposure
                one would want to drop by mistake, so it must be visible. */}
            {column.id === 'name' && reference && (
              <span title={m.selector_reference_mark()}>◎ </span>
            )}
            {column.id === 'rejected_by' && valeur
              ? (REJECT_LABEL[String(valeur)] ?? String(valeur))
              : format(valeur, column.digits)}
          </td>
        );
      })}
      <td style={{ width: '1%' }}>
        <button
          class="btn"
          style={{ padding: '1px 6px', fontSize: '11px' }}
          title={m.selector_open_frame_title()}
          onClick={(e) => {
            e.stopPropagation();
            openFrame(row.frame);
          }}
        >
          {m.selector_open()}
        </button>
      </td>
    </tr>
  );
}

function FrameTable() {
  const lignes = sortedRows.value;
  if (!lignes.length) return <Empty text={m.selector_group_not_measured()} />;
  return (
    <div style={{ overflowX: 'auto', maxHeight: '40vh', overflowY: 'auto' }}>
      <table class="data-table">
        <thead
          style={{ position: 'sticky', top: 0, background: 'var(--vscode-editor-background)' }}
        >
          <tr>
            <th title={m.selector_stack_this()} />
            {visibleColumns.value.map((column) => (
              <HeaderCell key={column.id} {...column} />
            ))}
            <th />
          </tr>
        </thead>
        <tbody>
          {lignes.map(({ row, index }) => (
            <FrameRow key={row.frame} row={row} index={index} />
          ))}
        </tbody>
      </table>
      <p style={{ margin: '4px 0 0', fontSize: '11px', color: MUTED }}>
        {m.selector_table_hint()}
      </p>
    </div>
  );
}

/**
 * The criteria, as Python expressions evaluated in a sandbox — like PixelMath.
 *
 * They receive the raw measurements and, for each one, the batch quantities `_min`, `_max`,
 * `_median`, `_sigma` and `_n`. **`_sigma` is the one to use for dropping**: `_n` is a min-max,
 * hence crushed by the very failed exposure one is trying to get rid of.
 */
function CriteriaPanel() {
  const valeurs = currentCriteria.value;
  if (!valeurs) return null;
  const faute = criteriaError.value;

  const champ = (
    key: keyof Criteria,
    label: string,
    placeholder: string,
    hint: string,
  ) => {
    const invalide = faute?.key === key;
    return (
      <div style={{ display: 'grid', gap: '2px' }}>
        <label style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '12px' }}>
          <span style={{ width: '150px', color: MUTED }} title={hint}>
            {label}
          </span>
          <input
            type="text"
            value={String(valeurs[key] ?? '')}
            placeholder={placeholder}
            title={hint}
            disabled={loading.value}
            aria-invalid={invalide}
            style={{ flex: 1, minWidth: 0 }}
            onChange={(e) => {
              const brut = (e.target as HTMLInputElement).value;
              const valeur = typeof valeurs[key] === 'number' ? Number(brut) : brut;
              if (typeof valeur === 'number' && !Number.isFinite(valeur)) return;
              void setCriteria({ [key]: valeur } as Partial<Criteria>);
            }}
          />
        </label>
        {invalide && (
          <p
            style={{
              margin: '0 0 0 158px',
              fontSize: '11px',
              color: 'var(--vscode-errorForeground)',
            }}
          >
            {faute.message}
          </p>
        )}
      </div>
    );
  };

  return (
    <div style={{ display: 'grid', gap: '6px' }}>
      {/* The placeholders of the last three fields are **expressions** and numbers: they stay
          as they are, like the Python code of the console. */}
      {champ(
        'approval',
        m.selector_criteria_approval(),
        m.selector_criteria_approval_placeholder(),
        m.selector_criteria_approval_hint(),
      )}
      {champ(
        'weighting',
        m.selector_criteria_weighting(),
        '65 + 5 * fwhm_n + 10 * eccentricity_n + 20 * snr_n',
        m.selector_criteria_weighting_hint(),
      )}
      {champ(
        'min_weight',
        m.selector_criteria_min_weight(),
        '0.05',
        m.selector_criteria_min_weight_hint(),
      )}
      {champ(
        'roundness_limit',
        m.selector_criteria_roundness(),
        '3.0',
        m.selector_criteria_roundness_hint(),
      )}
      <p style={{ margin: '2px 0 0', fontSize: '11px', color: MUTED }}>
        {m.selector_criteria_note()}
      </p>
    </div>
  );
}

function Actions() {
  const bilan = currentSummary.value;
  const total = rows.value.length;
  const rejets = measures.value?.rejects[currentGroup.value] ?? [];
  return (
    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
      <button
        class="btn"
        disabled={loading.value || !rejets.length}
        title={m.selector_reset_rejects_title()}
        onClick={() => void setRejects([])}
      >
        {m.selector_reset_rejects()}
      </button>
      <button
        class="btn"
        disabled={loading.value || !total}
        title={m.selector_freeze_title()}
        onClick={() => void freezeRejections()}
      >
        {m.selector_freeze()}
      </button>
      <button class="btn" disabled={loading.value} onClick={() => void loadMeasures()}>
        {m.selector_reload()}
      </button>
      {loading.value && <span style={{ fontSize: '12px', color: MUTED }}>…</span>}
      {bilan && (
        <span style={{ fontSize: '12px', color: MUTED }}>
          {plural(
            bilan.frames,
            m.selector_kept_summary_one({
              kept: bilan.frames,
              measured: bilan.measured,
              duration: formatDuration(bilan.integration),
            }),
            m.selector_kept_summary_many({
              kept: bilan.frames,
              measured: bilan.measured,
              duration: formatDuration(bilan.integration),
            }),
          )}
        </span>
      )}
    </div>
  );
}

export function SelectorTab() {
  // The plan carries the measurements: without it there is nothing to read back. We (re)load
  // on every change of plan, which covers "the run has just finished" as well as "the tab has
  // been reopened".
  useEffect(() => {
    void loadMeasures();
  }, [plan.value]);

  const groupes = groupKeys.value;

  return (
    <div style={{ padding: '16px 20px', overflowY: 'auto', height: '100%', fontSize: '13px' }}>
      <h2 style={{ font: 'inherit', fontSize: '15px', fontWeight: 600, margin: '0 0 14px' }}>
        {m.panel_selector()}
        {/* An indeterminate bar rather than a frozen screen: reading the measurements back
            and re-judging takes a few tens of milliseconds, but a slow network round trip
            would otherwise suggest the click did nothing. */}
        {loading.value && (
          <span style={{ marginLeft: '10px', fontSize: '11px', fontWeight: 400, color: MUTED }}>
            {m.selector_loading()}
          </span>
        )}
      </h2>

      {selectorError.value && (
        <p style={{ color: 'var(--vscode-errorForeground)' }}>{selectorError.value}</p>
      )}

      {!plan.value && <Empty text={m.selector_no_plan()} />}

      {plan.value && !hasMeasures.value && <Empty text={m.selector_no_measures()} />}

      {hasMeasures.value && (
        <Fragment>
          <Section title={m.selector_section_groups({ count: groupes.length })}>
            <GroupTable />
          </Section>

          <Section title={m.selector_section_frames({ group: currentGroup.value || '—' })}>
            <FrameTable />
          </Section>

          <Section title={m.selector_section_metrics()}>
            <MetricGrid />
          </Section>

          <Section title={m.selector_section_criteria()}>
            <CriteriaPanel />
          </Section>

          <Section title={m.selector_section_actions()}>
            <Actions />
          </Section>
        </Fragment>
      )}
    </div>
  );
}
