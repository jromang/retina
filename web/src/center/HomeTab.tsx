// Home screen — what one sees when nothing is open.
//
// The centre was never empty: it showed the "Desktop", that is, an empty grid of process
// icons, whose only text was "Drop a process's ⠿ handle here". A first launch therefore opened
// on an invitation to file away settings one does not have yet.
//
// Here, four paths, in the order in which they are needed: pick up where one left off (recent
// projects, previous session), reopen a recent image, open a first one, or go and read. Every
// action goes through the command registry or through an `app.*` — nothing reserved for this
// page.

import { useState } from 'preact/hooks';

import { client } from '../api/client';
import { awaitJob } from '../processes/jobs';
import { m } from '../paraglide/messages';
import {
  currentProject,
  hasAutosession,
  openProject,
  recentFiles,
  recentProjects,
} from '../project/project';
import { folder as pipelineFolder, preset as pipelinePreset, scan as pipelineScan }
  from '../pipeline/model';
import { requestActivate } from '../shell/layoutClient';
import { startTour } from '../shell/Tour';
import { askPath } from '../shell/native';
import { GETTING_STARTED, openGuide } from './docTarget';

const MUTED = 'var(--vscode-descriptionForeground)';

// The discovery walkthrough, on the documentation side. The `_guides/` prefix cannot collide
// with a `process_id` (a class name), so the identifier travels the same route and the same
// viewer as any process page.

function shortName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function directory(path: string): string {
  const separator = path.includes('\\') && !path.includes('/') ? '\\' : '/';
  const cut = path.lastIndexOf(separator);
  return cut > 0 ? path.slice(0, cut) : '';
}

function Section({ title, children }: { title: string; children: preact.ComponentChildren }) {
  return (
    <section style={{ marginBottom: '28px' }}>
      <h2 style={{ margin: '0 0 8px', fontSize: '13px', fontWeight: 600, color: MUTED }}>
        {title}
      </h2>
      {children}
    </section>
  );
}

function PathList({
  paths,
  vide,
  onPick,
}: {
  paths: readonly string[];
  vide: string;
  onPick: (path: string) => void;
}) {
  if (paths.length === 0) {
    return <p style={{ margin: 0, fontSize: '12px', color: MUTED }}>{vide}</p>;
  }
  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {paths.map((path) => (
        <li key={path}>
          <button
            type="button"
            class="btn"
            title={path}
            onClick={() => onPick(path)}
            style={{
              display: 'flex',
              alignItems: 'baseline',
              gap: '8px',
              width: '100%',
              padding: '3px 6px',
              background: 'transparent',
              border: 'none',
              textAlign: 'left',
            }}
          >
            <span style={{ color: 'var(--vscode-textLink-foreground)' }}>{shortName(path)}</span>
            <span
              style={{
                flex: 1,
                minWidth: 0,
                fontSize: '11px',
                color: MUTED,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                direction: 'rtl',
                textAlign: 'left',
              }}
            >
              {directory(path)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function HomeTab() {
  // The download is a **job**: the status bar shows its progress and offers to cancel it, like
  // any long operation. This flag only greys the button so it is not started twice.
  const [chargement, setChargement] = useState(false);

  const ouvrirGuide = () => openGuide(GETTING_STARTED);

  // A downloaded set that stayed a folder in a cache would have made nobody discover
  // anything: we chain on to preprocessing, exactly where those raw frames are of use.
  const ouvrirExemple = () => {
    if (chargement) return;
    setChargement(true);
    void client
      .call<{ job: string }>('app.download_sample', {})
      .then(({ job }) => awaitJob(job))
      .then((result) => {
        // Cancelled, or failed: the notification centre has already said so, and there is
        // nothing to scan. Chaining anyway would open the wizard on an empty folder.
        const path = result?.['folder'];
        if (typeof path !== 'string') return;
        pipelinePreset.value = 'auto';
        pipelineFolder.value = path;
        requestActivate('pipeline');
        return pipelineScan(path);
      })
      .catch((e: unknown) => console.error(e))
      .finally(() => setChargement(false));
  };

  const ouvrirImage = () => {
    void askPath({ title: m.dialog_open_image() }).then((paths) => {
      if (paths?.[0]) {
        // `app.open`, hence echoed: opening from home writes the same line as the console.
        void client.call('app.open', { path: paths[0] }).catch((e: unknown) => console.error(e));
      }
    });
  };

  // A smart telescope's folder is an entry in its own right, and not merely a shortcut: these
  // devices produce hundreds of short exposures that the generic preset would group badly
  // (unregulated sensor — without the temperature tolerance, every exposure would make its own
  // dark group). The gesture therefore sets the preset **before** scanning. This is not a real
  // folder drop: the native shell does not relay the system's file-drops yet, so the folder
  // picker stands in for it.
  const ouvrirSeestar = () => {
    void askPath({ title: m.home_seestar_title(), folder: true }).then((paths) => {
      const path = paths?.[0];
      if (!path) return;
      pipelinePreset.value = 'seestar';
      pipelineFolder.value = path;
      requestActivate('pipeline');
      void pipelineScan(path);
    });
  };

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '32px 40px' }}>
      <h1 style={{ margin: '0 0 4px', fontSize: '24px', fontWeight: 300 }}>Retina</h1>
      <p style={{ margin: '0 0 32px', fontSize: '13px', color: MUTED }}>{m.home_tagline()}</p>

      <div style={{ display: 'flex', gap: '48px', flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <Section title={m.home_resume()}>
            <PathList
              paths={recentProjects.value}
              vide={m.home_no_recent_projects()}
              onPick={(path) => void openProject(path).catch((e: unknown) => console.error(e))}
            />
            {hasAutosession.value && !currentProject.value && (
              <p style={{ margin: '8px 0 0' }}>
                <button
                  type="button"
                  class="btn"
                  onClick={() => {
                    // The server knows the path of its implicit session; we do not guess it on
                    // the client side. `project.open` without a path would leave it to guess,
                    // hence going through the recents list, which holds it as soon as it
                    // exists.
                    void client
                      .call<{ recent_projects: string[] }>('project.recent')
                      .then((etat) => {
                        const dernier = etat.recent_projects[0];
                        if (dernier) return openProject(dernier);
                        return undefined;
                      })
                      .catch((e: unknown) => console.error(e));
                  }}
                >
                  {m.home_reopen_session()}
                </button>
              </p>
            )}
          </Section>

          <Section title={m.home_recent_images()}>
            <PathList
              paths={recentFiles.value}
              vide={m.home_no_recent_images()}
              onPick={(path) => {
                void client.call('app.open', { path }).catch((e: unknown) => console.error(e));
              }}
            />
          </Section>
        </div>

        <div style={{ flex: '0 1 300px', minWidth: 0 }}>
          <Section title={m.home_start()}>
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: '6px' }}>
              <li>
                <button type="button" class="btn" onClick={ouvrirImage} style={{ width: '100%' }}>
                  <i class="codicon codicon-file-media" aria-hidden="true" />{' '}
                  {m.home_first_image()}
                </button>
              </li>
              <li>
                <button
                  type="button"
                  class="btn"
                  style={{ width: '100%' }}
                  onClick={() => requestActivate('pipeline')}
                >
                  {/* Same label as the like-named command: it is the same gesture. */}
                  <i class="codicon codicon-run-all" aria-hidden="true" /> {m.cmd_pipeline_show()}
                </button>
              </li>
              <li>
                <button
                  type="button"
                  class="btn"
                  style={{ width: '100%' }}
                  onClick={ouvrirSeestar}
                  title={m.home_seestar_tip()}
                >
                  <i class="codicon codicon-telescope" aria-hidden="true" />{' '}
                  {m.home_seestar()}
                </button>
              </li>
              <li>
                <button
                  type="button"
                  class="btn"
                  style={{ width: '100%' }}
                  onClick={() => requestActivate('doc')}
                >
                  <i class="codicon codicon-book" aria-hidden="true" /> {m.home_doc()}
                </button>
              </li>
            </ul>
          </Section>

          <Section title={m.home_discover()}>
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: '6px' }}>
              <li>
                <button
                  type="button"
                  class="btn"
                  style={{ width: '100%' }}
                  onClick={ouvrirGuide}
                  title={m.home_guide_tip()}
                >
                  <i class="codicon codicon-compass" aria-hidden="true" /> {m.home_guide()}
                </button>
              </li>
              <li>
                {/* The tour ran once, at the first launch, and then existed only as a palette
                    command — so the one gesture that shows where things are was, after that
                    day, findable only by someone who no longer needed it. */}
                <button
                  type="button"
                  class="btn"
                  style={{ width: '100%' }}
                  onClick={() => startTour()}
                  title={m.home_tour_tip()}
                >
                  <i class="codicon codicon-lightbulb" aria-hidden="true" /> {m.home_tour()}
                </button>
              </li>
              <li>
                <button
                  type="button"
                  class="btn"
                  style={{ width: '100%' }}
                  onClick={ouvrirExemple}
                  disabled={chargement}
                  title={m.home_sample_tip()}
                >
                  <i
                    class={chargement ? 'codicon codicon-sync' : 'codicon codicon-cloud-download'}
                    aria-hidden="true"
                  />{' '}
                  {chargement ? m.home_sample_busy() : m.home_sample()}
                </button>
              </li>
            </ul>
            <p style={{ margin: '6px 0 0', fontSize: '11px', color: MUTED }}>
              {m.home_sample_credit()}
            </p>
          </Section>
        </div>
      </div>
    </div>
  );
}
