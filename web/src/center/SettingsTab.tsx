// Preferences panel — one more client of `app.preferences`, nothing else.
//
// It has no logic of its own: the schema comes from the server (`preferences.describe`), the
// fields are those of the auto-generated process form (`fieldFor`), and every change leaves as
// `preferences.set`. Typing the same setting in the console does exactly the same thing, and
// the panel learns of it through the `preferences.changed` notification — that is the parity
// rule, applied in both directions.
//
// A centre tab rather than a zone panel: it is a wide read, and it has nothing to do with the
// active image.

import { useEffect, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';
import { fieldFor } from '../processes/fields';
import type { ParameterMeta } from '../api/types';

interface PreferenceEntry extends ParameterMeta {
  value: unknown;
}

interface PreferenceGroup {
  id: string;
  label: string;
  parameters: PreferenceEntry[];
}

const groupStyle = {
  margin: '0 0 18px 0',
};

const titleStyle = {
  fontSize: '11px',
  textTransform: 'uppercase' as const,
  letterSpacing: '0.06em',
  color: 'var(--vscode-descriptionForeground)',
  margin: '0 0 8px 0',
  paddingBottom: '4px',
  borderBottom: '1px solid var(--vscode-panel-border)',
};

const gridStyle = {
  display: 'grid',
  gridTemplateColumns: 'auto 1fr',
  gap: '6px 10px',
  alignItems: 'center',
};

export function SettingsTab() {
  const [groups, setGroups] = useState<PreferenceGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    client
      .call<PreferenceGroup[]>('preferences.describe')
      .then((data) => {
        setGroups(data);
        setError(null);
      })
      .catch((reason: unknown) => setError(String(reason)));
  };

  useEffect(() => {
    reload();
    // A setting made in the console must show up here without reopening the tab.
    return client.onNotification((method) => {
      if (method === 'preferences.changed') reload();
    });
  }, []);

  if (error) {
    return <p style={{ margin: '12px', fontSize: '12px' }}>{error}</p>;
  }
  if (!groups) {
    return <p style={{ margin: '12px', fontSize: '12px' }}>{m.settings_loading()}</p>;
  }

  const change = (key: string, value: unknown) => {
    client
      .call('preferences.set', { key, value })
      .then(reload)
      .catch((reason: unknown) => setError(String(reason)));
  };

  return (
    <div style={{ padding: '12px 16px', overflowY: 'auto', height: '100%', fontSize: '12px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', marginBottom: '14px' }}>
        <h2 style={{ margin: 0, fontSize: '14px', fontWeight: 600 }}>{m.panel_settings()}</h2>
        <button
          onClick={() => {
            client.call('preferences.reset').then(reload).catch(() => undefined);
          }}
        >
          {m.settings_reset_all()}
        </button>
      </div>
      {groups.map((group) => (
        <section key={group.id} style={groupStyle}>
          <h3 style={titleStyle}>{group.label}</h3>
          <div style={gridStyle}>
            {group.parameters.map((parameter) => {
              const Field = fieldFor(parameter.type);
              return [
                <label key={`${parameter.id}-l`} title={parameter.tooltip} for={parameter.id}>
                  {parameter.label}
                </label>,
                <Field
                  key={parameter.id}
                  param={parameter}
                  value={parameter.value}
                  onChange={(next: unknown) => change(parameter.id, next)}
                />,
              ];
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
