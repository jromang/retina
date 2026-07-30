// "Licences" panel — what Retina bundles, and under what conditions.
//
// One more client of `retina.credits`, like the rest: the console returns the same thing with
// `app.credits()`. Nothing is computed here.
//
// Project names, SPDX expressions and URLs are not translated: they are identifiers, not
// prose. Only the family headings are.

import { useEffect, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { client } from '../api/client';

interface Credit {
  id: string;
  name: string;
  kind: string;
  license: string;
  version: string;
  copyright: string;
  url: string;
  notice: string;
  note: string;
}

interface CreditsPayload {
  kinds: string[];
  components: Credit[];
  summary: Record<string, number>;
}

function familyLabel(kind: string): string {
  switch (kind) {
    case 'asset':
      return m.credits_kind_asset();
    case 'frontend':
      return m.credits_kind_frontend();
    case 'native':
      return m.credits_kind_native();
    case 'python':
      return m.credits_kind_python();
    case 'download':
      return m.credits_kind_download();
    default:
      return kind;
  }
}

const headingStyle = {
  fontSize: '11px',
  textTransform: 'uppercase' as const,
  letterSpacing: '0.06em',
  color: 'var(--vscode-descriptionForeground)',
  margin: '18px 0 6px 0',
  paddingBottom: '4px',
  borderBottom: '1px solid var(--vscode-panel-border)',
};

const rowStyle = {
  display: 'grid',
  gridTemplateColumns: 'minmax(180px, 1fr) auto',
  gap: '4px 14px',
  padding: '5px 0',
  alignItems: 'baseline',
  borderBottom: '1px solid var(--vscode-panel-border)',
};

export function CreditsTab() {
  const [data, setData] = useState<CreditsPayload | null>(null);
  const [notice, setNotice] = useState<{ name: string; text: string } | null>(null);

  useEffect(() => {
    client
      .call<CreditsPayload>('credits.list')
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (!data) {
    return <p style={{ margin: '12px', fontSize: '12px' }}>{m.credits_loading()}</p>;
  }

  if (notice) {
    return (
      <div style={{ padding: '12px 16px', height: '100%', overflowY: 'auto' }}>
        <button onClick={() => setNotice(null)} style={{ marginBottom: '10px' }}>
          ← {m.credits_back()}
        </button>
        <h3 style={{ margin: '0 0 8px 0', fontSize: '13px' }}>{notice.name}</h3>
        <pre
          style={{
            fontSize: '11px',
            whiteSpace: 'pre-wrap',
            fontFamily: 'var(--vscode-editor-font-family, monospace)',
          }}
        >
          {notice.text}
        </pre>
      </div>
    );
  }

  return (
    <div style={{ padding: '12px 16px', height: '100%', overflowY: 'auto', fontSize: '12px' }}>
      <h2 style={{ margin: '0 0 4px 0', fontSize: '14px', fontWeight: 600 }}>
        {m.panel_credits()}
      </h2>
      <p style={{ margin: '0 0 8px 0', color: 'var(--vscode-descriptionForeground)' }}>
        {m.credits_intro()}
      </p>

      {data.kinds.map((kind) => {
        const group = data.components.filter((c) => c.kind === kind);
        if (group.length === 0) return null;
        return (
          <section key={kind}>
            <h3 style={headingStyle}>
              {familyLabel(kind)} ({group.length})
            </h3>
            {group.map((credit) => (
              <div key={credit.id} style={rowStyle}>
                <div>
                  <strong>{credit.name}</strong>
                  {credit.version ? (
                    <span style={{ color: 'var(--vscode-descriptionForeground)' }}>
                      {' '}
                      {credit.version}
                    </span>
                  ) : null}
                  {credit.note ? (
                    <div
                      style={{
                        color: 'var(--vscode-descriptionForeground)',
                        marginTop: '2px',
                        maxWidth: '70ch',
                      }}
                    >
                      {credit.note}
                    </div>
                  ) : null}
                  {credit.copyright ? (
                    <div
                      style={{ color: 'var(--vscode-descriptionForeground)', marginTop: '2px' }}
                    >
                      {credit.copyright}
                    </div>
                  ) : null}
                </div>
                <div style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                  <div>{credit.license || '—'}</div>
                  {credit.url ? (
                    <a href={credit.url} target="_blank" rel="noreferrer" style={{ fontSize: '11px' }}>
                      {m.credits_website()}
                    </a>
                  ) : null}
                  {credit.notice ? (
                    <>
                      {credit.url ? ' · ' : null}
                      <a
                        href="#"
                        style={{ fontSize: '11px' }}
                        onClick={(event) => {
                          event.preventDefault();
                          void client
                            .call<string>('credits.notice', { id: credit.id })
                            .then((text) => setNotice({ name: credit.name, text }));
                        }}
                      >
                        {m.credits_full_text()}
                      </a>
                    </>
                  ) : null}
                </div>
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}
