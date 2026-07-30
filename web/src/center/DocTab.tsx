// Documentation tab.
//
// [RETHOUGHT vs the Qt shell] There the doc occupies a narrow dock on the right; this is long
// reading, its place is in the centre, at the width of the text. F1 opens it here.
//
// The HTML comes entirely from the domain (`documentation.render_page`: Markdown + KaTeX +
// Pygments), served over HTTP with its asset base rewritten. An `iframe` isolates it: the
// doc's CSS cannot leak into the shell, nor the other way round.
//
// The internal links use the `retina-doc://<pid>` scheme, a contract kept from the Qt shell —
// we intercept it to navigate without the network.

import { useEffect, useRef, useState } from 'preact/hooks';

import { client } from '../api/client';
import { m } from '../paraglide/messages';
import { getLocale } from '../paraglide/runtime';
import { processes } from '../state/store';
import { docTarget, takeDocTarget } from './docTarget';

export function DocTab() {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [html, setHtml] = useState<string>('');

  const load = (processId: string | null) => {
    // The doc is already bilingual on the server side: `/api/doc/…` accepts a `?lang=` and
    // returns the page in that language. Without the parameter, the server falls back on its
    // default — this is the only place in the shell where the language must travel through
    // the URL rather than through `m`.
    const base = processId ? `/api/doc/${encodeURIComponent(processId)}` : '/api/doc/';
    const path = `${base}?lang=${encodeURIComponent(getLocale())}`;
    void client
      .fetch(path)
      .then((response) => response.text())
      .then(setHtml)
      .catch((error: unknown) => console.error('documentation', error));
    setCurrent(processId);
  };

  useEffect(() => {
    // A target set before mounting (assistant, command) wins over the index.
    load(takeDocTarget());
  }, []);

  // Target set while the tab is already mounted: we navigate, pushing the history as a click
  // on an internal link would.
  useEffect(() => {
    const unsubscribe = docTarget.subscribe((target) => {
      if (target === null) return;
      docTarget.value = null;
      setHistory((previous) => [...previous, current ?? '']);
      load(target);
    });
    return unsubscribe;
  }, [current]);

  // Direct writing into the iframe rather than a `src`: the page is authenticated by a header,
  // and an iframe cannot set one.
  useEffect(() => {
    const frame = frameRef.current;
    const document_ = frame?.contentDocument;
    if (!frame || !document_ || !html) return;
    document_.open();
    document_.write(html);
    document_.close();

    const onClick = (event: MouseEvent) => {
      const anchor = (event.target as HTMLElement | null)?.closest('a');
      const href = anchor?.getAttribute('href') ?? '';
      if (!href.startsWith('retina-doc://')) return;
      event.preventDefault();
      const target = href.slice('retina-doc://'.length).replace(/\/$/, '');
      setHistory((previous) => [...previous, current ?? '']);
      load(target);
    };
    document_.addEventListener('click', onClick);
    return () => document_.removeEventListener('click', onClick);
  }, [html]);

  const back = () => {
    const previous = history.at(-1);
    if (previous === undefined) return;
    setHistory((entries) => entries.slice(0, -1));
    load(previous || null);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '4px',
          padding: '2px 8px',
          borderBottom: '1px solid var(--vscode-panel-border)',
          background: 'var(--vscode-editorWidget-background)',
        }}
      >
        <button
          onClick={back}
          disabled={history.length === 0}
          title={m.doc_back()}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--vscode-foreground)',
            cursor: history.length ? 'pointer' : 'default',
            opacity: history.length ? 1 : 0.4,
            fontSize: '14px',
          }}
        >
          <i class="codicon codicon-arrow-left" aria-hidden="true" />
        </button>
        <button
          onClick={() => load(null)}
          title={m.doc_home_title()}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--vscode-foreground)',
            cursor: 'pointer',
            fontSize: '14px',
          }}
        >
          <i class="codicon codicon-home" aria-hidden="true" />
        </button>
        <select
          value={current ?? ''}
          onChange={(event) => {
            const next = (event.target as HTMLSelectElement).value;
            setHistory((entries) => [...entries, current ?? '']);
            load(next || null);
          }}
          style={{
            background: 'var(--vscode-dropdown-background)',
            color: 'var(--vscode-dropdown-foreground)',
            border: '1px solid var(--vscode-dropdown-border)',
            borderRadius: '2px',
            font: '12px var(--retina-font-ui)',
            padding: '1px 4px',
          }}
        >
          <option value="">{m.panel_home()}</option>
          {processes.value
            .filter((process) => process.has_doc)
            .map((process) => (
              <option key={process.process_id} value={process.process_id}>
                {process.process_id}
              </option>
            ))}
        </select>
      </div>
      <iframe
        ref={frameRef}
        title={m.panel_doc()}
        sandbox="allow-same-origin allow-scripts"
        style={{ flex: 1, border: 'none', background: 'var(--vscode-editor-background)' }}
      />
    </div>
  );
}
