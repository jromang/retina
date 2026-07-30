// The field grid auto-generated from `Process.parameters` — extracted from `ProcessPanel` so
// that the pipeline wizard's step editor reuses it rather than rewriting it.
//
// This is the consequence of an architectural choice, not an opportunistic factorisation: the
// parameter schema is the single source of the form, and a second home-made rendering would
// have diverged with the first field type added. The preferences panel already calls
// `fieldFor` for the same reason.
//
// `readOnly` serves the parameters the wizard must not let anyone touch: those carrying a late
// binding (`@reference`, `@weights`) and the paths the plan's graph computes. Showing them
// greyed out is better than hiding them — their value explains what the step is going to do.

import type { ParameterMeta } from '../api/types';
import { fieldFor, isVisible } from './fields';

interface Props {
  parameters: readonly ParameterMeta[];
  values: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  /** Parameters shown but not editable, with the reason in a tooltip. */
  readOnly?: Readonly<Record<string, string>>;
}

export function ParameterGrid({ parameters, values, onChange, readOnly }: Props) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 10px' }}>
      {parameters.filter((param) => isVisible(param, values)).map((param) => {
        const Field = fieldFor(param.type);
        const verrou = readOnly?.[param.id];
        return [
          <label
            key={`${param.id}-label`}
            title={verrou ? `${param.tooltip}\n${verrou}` : param.tooltip}
            style={{
              fontSize: '12px',
              color: 'var(--vscode-descriptionForeground)',
              textAlign: 'right',
              alignSelf: 'center',
              whiteSpace: 'nowrap',
              opacity: verrou ? 0.6 : 1,
            }}
          >
            {param.label}
          </label>,
          <div
            key={param.id}
            title={verrou || undefined}
            style={
              verrou
                ? { opacity: 0.6, pointerEvents: 'none' as const }
                : undefined
            }
          >
            <Field
              param={param}
              value={values[param.id]}
              onChange={(value) => onChange({ ...values, [param.id]: value })}
            />
          </div>,
        ];
      })}
    </div>
  );
}
