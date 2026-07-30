// Centre zone — one dockview tab per open image.
//
// dockview is imperative and manipulates the DOM directly; Preact is declarative. The bridge
// is `PreactRenderer`: dockview owns the element, Preact renders inside it. It is the same
// technique used to integrate React with dockview, in about twenty lines.
//
// The synchronisation is one-way: the server snapshot decides which tabs exist. Closing a tab
// calls `app.close_window`, which will produce a new snapshot in which the window is gone — we
// never remove the tab ourselves. It is one round trip slower, and it is what guarantees that
// an `app.close_window()` typed in the console does exactly the same thing as a click on the
// cross.

import { createDockview, type DockviewApi, type IContentRenderer } from 'dockview-core';
import { render } from 'preact';
import { useLayoutEffect, useRef } from 'preact/hooks';

import { client } from '../api/client';
import type { WindowState } from '../api/types';
import { m } from '../paraglide/messages';
import { snapshot, windows } from '../state/store';
import { ViewportPanel, type ViewportStatus } from '../viewport/ViewportPanel';
import { DesktopTab } from './DesktopTab';
import { PipelineTab } from './PipelineTab';
import { CreditsTab } from './CreditsTab';
import { SettingsTab } from './SettingsTab';
import { LightCurveTab } from './LightCurveTab';
import { SelectorTab } from './SelectorTab';
import { DocTab } from './DocTab';
import { HomeTab } from './HomeTab';
import { panelVisible, requestToggle } from '../shell/layoutClient';
import { RtpPanel } from '../processes/RtpPanel';
import { rtpOwners } from '../processes/rtp';
import { ScriptTab } from '../scripts/ScriptTab';
import { SCRIPT_PREFIX, closeScript, openScripts, type ScriptDoc } from '../scripts/scripts';
import { ContainerTab, titleForContainer } from './ContainerTab';
import { CONTAINER_PREFIX, closeContainer, openContainers } from '../pipeline/containerEdit';
import { setDockProvider, takePendingActiveTab } from '../project/documents';
import { confirmBox } from '../ui/prompts';

interface Props {
  onStatus: (status: ViewportStatus) => void;
}

/** dockview → Preact adapter: dockview owns the element, Preact paints inside it. */
class PreactRenderer implements IContentRenderer {
  readonly element = document.createElement('div');

  constructor(private readonly draw: (host: HTMLElement) => void) {
    this.element.style.height = '100%';
    this.element.style.width = '100%';
  }

  init(): void {
    this.draw(this.element);
  }

  update(): void {
    this.draw(this.element);
  }

  dispose(): void {
    render(null, this.element);
  }
}

export function CenterDock({ onStatus }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<DockviewApi | null>(null);
  // The drawers are kept so they can be redrawn when the snapshot changes.
  const drawersRef = useRef(new Map<string, (host: HTMLElement) => void>());
  // Last window we brought to the front. Without this memory, every snapshot — and there is
  // one per action — would bring the active window forward, chasing away the Documentation or
  // Preprocessing tab the user has just opened.
  const activatedRef = useRef<string | null>(null);

  const DESKTOP_ID = 'desktop';
  const RTP_ID = 'rtp-preview';
  const DOC_ID = 'doc-tab';
  const HOME_ID = 'home-tab';
  const PIPELINE_ID = 'pipeline-tab';
  const SETTINGS_ID = 'settings-tab';
  const CREDITS_ID = 'credits-tab';
  const SELECTOR_ID = 'selector-tab';
  const LIGHTCURVE_ID = 'lightcurve-tab';
  /** Permanent tabs of the centre: they correspond to no image window. The previews are
   *  prefixed `rtp-preview:` — there is one per form — and the scripts `script:`, one per
   *  open document. */
  const FIXED = [DESKTOP_ID, DOC_ID, HOME_ID, PIPELINE_ID, SELECTOR_ID, LIGHTCURVE_ID,
                 SETTINGS_ID, CREDITS_ID];
  const isFixed = (id: string) =>
    FIXED.includes(id) ||
    id.startsWith(`${RTP_ID}:`) ||
    id.startsWith(SCRIPT_PREFIX) ||
    id.startsWith(CONTAINER_PREFIX);

  const drawerFor = (windowId: string) => (host: HTMLElement) => {
    const win = windows.value.find((w) => w.id === windowId);
    if (!win) return;
    const view = win.views.find((v) => v.id === win.current_view) ?? win.views[0];
    if (!view) return;
    render(<ViewportPanel window={win} view={view} onStatus={onStatus} />, host);
  };

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const api = createDockview(host, {
      className: 'dockview-theme-dark',
      createComponent: (options) => {
        const draw = drawersRef.current.get(options.id);
        return new PreactRenderer(draw ?? (() => undefined));
      },
    });
    apiRef.current = api;

    const closed = api.onDidRemovePanel((panel) => {
      // Cross of the Home tab: the server mirror must follow, otherwise `panelVisible.home`
      // would stay true and the next reconciliation would reopen it. The guard avoids the
      // reverse loop — it is also this reconciliation that removes the panel when the signal
      // turns false, and a `requestToggle` at that moment would switch it back on.
      if (panel.id === HOME_ID) {
        if (panelVisible.value.home) requestToggle('home');
        return;
      }
      // Tab closed with the mouse: we tell the domain, which will decide.
      if (!isFixed(panel.id) && windows.value.some((w) => w.id === panel.id)) {
        void client
          .call('app.close_window', { window: panel.id })
          .catch((error: unknown) => console.error(error));
        return;
      }
      // A script is a document saved nowhere else: dockview has already removed the tab (it
      // offers no veto), so we recreate it if the user backs out. The back-and-forth is
      // visible, but losing a script without warning would be far more so.
      if (panel.id.startsWith(SCRIPT_PREFIX)) {
        const doc = openScripts.value.find((entry) => entry.id === panel.id);
        if (!doc) return;
        if (!doc.dirty) {
          closeScript(panel.id);
          return;
        }
        void confirmBox(m.center_script_unsaved({ title: doc.title }), m.prompt_close()).then(
          (confirmed) => {
            if (confirmed) {
              closeScript(panel.id);
              return;
            }
            api.addPanel({ id: panel.id, component: panel.id, title: titleForScript(doc) });
            api.getPanel(panel.id)?.api.setActive();
          },
        );
        return;
      }
      // Same treatment for a recipe: a recipe being written, with its disabled steps and its
      // masks, exists nowhere else as long as it has not been filed into the library. Closing
      // it without asking anything was an asymmetry with the scripts, not a decision.
      if (panel.id.startsWith(CONTAINER_PREFIX)) {
        const doc = openContainers.value.find((entry) => entry.id === panel.id);
        if (!doc) return;
        if (!doc.dirty) {
          closeContainer(panel.id);
          return;
        }
        void confirmBox(m.center_container_unsaved({ title: doc.title }), m.prompt_close()).then(
          (confirmed) => {
            if (confirmed) {
              closeContainer(panel.id);
              return;
            }
            api.addPanel({
              id: panel.id,
              component: panel.id,
              title: titleForContainer(panel.id),
            });
            api.getPanel(panel.id)?.api.setActive();
          },
        );
      }
    });

    // What `serializeDocuments` will come and fetch. Injected rather than imported, so that
    // `project/documents.ts` stays testable without a DOM.
    setDockProvider(() => ({ activeTab: api.activePanel?.id ?? null }));

    return () => {
      setDockProvider(null);
      closed.dispose();
      api.dispose();
      apiRef.current = null;
      drawersRef.current.clear();
    };
  }, []);

  // Reconciliation tabs ⇄ snapshot.
  useLayoutEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    const list: WindowState[] = [...windows.value];
    const wanted = new Set(list.map((w) => w.id));

    for (const panel of api.panels) {
      if (!isFixed(panel.id) && !wanted.has(panel.id)) {
        api.removePanel(panel);
      }
    }

    // Desktop: permanent tab, created once and never removed.
    drawersRef.current.set(DESKTOP_ID, (host) => render(<DesktopTab />, host));
    if (!api.getPanel(DESKTOP_ID)) {
      api.addPanel({ id: DESKTOP_ID, component: DESKTOP_ID, title: m.panel_desktop() });
    }

    for (const win of list) {
      drawersRef.current.set(win.id, drawerFor(win.id));
      const existing = api.getPanel(win.id);
      if (existing) {
        existing.api.updateParameters({ rev: snapshot.value?.rev ?? 0 });
        existing.api.setTitle(titleFor(win));
      } else {
        api.addPanel({
          id: win.id,
          component: win.id,
          title: titleFor(win),
        });
      }
    }

    const activeId = snapshot.value?.active_window;
    if (activeId && activeId !== activatedRef.current) {
      api.getPanel(activeId)?.api.setActive();
    }
    activatedRef.current = activeId ?? null;

    // [RETHOUGHT] The preview opens as a SPLIT of the active viewport, not in a bottom dock:
    // comparing before/after means seeing them side by side. And **one panel per form** that
    // asks for one: the question one asks in front of two settings is "which of the two",
    // which a single preview cannot answer.
    const wantedRtp = new Set(rtpOwners.value.map((owner) => `${RTP_ID}:${owner}`));
    for (const panel of api.panels) {
      if (panel.id.startsWith(`${RTP_ID}:`) && !wantedRtp.has(panel.id)) {
        api.removePanel(panel);
      }
    }
    for (const owner of rtpOwners.value) {
      const id = `${RTP_ID}:${owner}`;
      drawersRef.current.set(id, (host) => render(<RtpPanel owner={owner} />, host));
      if (api.getPanel(id)) continue;
      // `exactOptionalPropertyTypes` forbids passing `position: undefined`: the key is only
      // added if we have a reference, otherwise dockview places the panel on its own.
      api.addPanel({
        id,
        component: id,
        title: `⚡ ${owner}`,
        ...(activeId ? { position: { referencePanel: activeId, direction: 'right' as const } } : {}),
      });
    }

    // The scripts: one tab per document, same mechanics as the previews. Their existence is
    // not a *domain* state — an open editor changes nothing about the images — hence a client
    // signal rather than one more panel in the `panels.ts` contract.
    const wantedScripts = new Set(openScripts.value.map((doc) => doc.id));
    for (const panel of api.panels) {
      if (panel.id.startsWith(SCRIPT_PREFIX) && !wantedScripts.has(panel.id)) {
        api.removePanel(panel);
      }
    }
    for (const doc of openScripts.value) {
      drawersRef.current.set(doc.id, (host) => render(<ScriptTab id={doc.id} />, host));
      const existingScript = api.getPanel(doc.id);
      if (existingScript) {
        existingScript.api.setTitle(titleForScript(doc));
        continue;
      }
      api.addPanel({ id: doc.id, component: doc.id, title: titleForScript(doc) });
      api.getPanel(doc.id)?.api.setActive();
    }

    // The recipes: one tab per recipe being edited, as the Qt shell did with one dock per
    // library entry.
    const wantedContainers = new Set(openContainers.value.map((doc) => doc.id));
    for (const panel of api.panels) {
      if (panel.id.startsWith(CONTAINER_PREFIX) && !wantedContainers.has(panel.id)) {
        api.removePanel(panel);
      }
    }
    for (const doc of openContainers.value) {
      drawersRef.current.set(doc.id, (host) => render(<ContainerTab id={doc.id} />, host));
      const existingContainer = api.getPanel(doc.id);
      if (existingContainer) {
        existingContainer.api.setTitle(titleForContainer(doc.id));
        continue;
      }
      api.addPanel({ id: doc.id, component: doc.id, title: titleForContainer(doc.id) });
      api.getPanel(doc.id)?.api.setActive();
    }

    // [RETHOUGHT] The documentation is long reading: in the centre, not in a narrow dock. Its
    // visibility remains driven by `app.layout.show('doc')`.
    drawersRef.current.set(DOC_ID, (host) => render(<DocTab />, host));
    const existingDoc = api.getPanel(DOC_ID);
    if (panelVisible.value.doc && !existingDoc) {
      api.addPanel({ id: DOC_ID, component: DOC_ID, title: m.panel_doc() });
    } else if (!panelVisible.value.doc && existingDoc) {
      api.removePanel(existingDoc);
    }

    // Home is a centre tab like the others, driven by `panelVisible.home`: it opens from the
    // console (`app.layout.show('home')`), from the palette, or on its own when the session is
    // empty — it is `connectProject` that makes that decision, once, at the `hello`.
    // **Without `setActive`**, unlike preprocessing and the selector. Its visibility persists
    // on the server side, so the tab is recreated at every page reload: bringing it to the
    // front would put it in front of the image or the script one was working on. On an empty
    // session it is alone anyway, hence active.
    drawersRef.current.set(HOME_ID, (host) => render(<HomeTab />, host));
    const existingHome = api.getPanel(HOME_ID);
    if (panelVisible.value.home && !existingHome) {
      api.addPanel({ id: HOME_ID, component: HOME_ID, title: m.panel_home() });
    } else if (!panelVisible.value.home && existingHome) {
      api.removePanel(existingHome);
    }

    // Preprocessing is a long walkthrough, with a table and a log: it needs the width of the
    // centre, not a side dock. Its visibility comes from the server, so
    // `app.layout.show('pipeline')` opens it from the console — parity demands it.
    drawersRef.current.set(PIPELINE_ID, (host) => render(<PipelineTab />, host));
    const existingPipeline = api.getPanel(PIPELINE_ID);
    if (panelVisible.value.pipeline && !existingPipeline) {
      api.addPanel({ id: PIPELINE_ID, component: PIPELINE_ID, title: m.panel_pipeline() });
      // …and to the front: the reconciliation above has just reactivated the active window,
      // which would leave the tab open but hidden behind an image.
      api.getPanel(PIPELINE_ID)?.api.setActive();
    } else if (!panelVisible.value.pipeline && existingPipeline) {
      api.removePanel(existingPipeline);
    }

    // The preferences: same reason for putting them in the centre — a wide read, unrelated to
    // the active image. Their visibility comes from the server, so `app.layout.show('settings')`
    // opens them from the console.
    drawersRef.current.set(SETTINGS_ID, (host) => render(<SettingsTab />, host));
    const existingSettings = api.getPanel(SETTINGS_ID);
    if (panelVisible.value.settings && !existingSettings) {
      api.addPanel({ id: SETTINGS_ID, component: SETTINGS_ID, title: m.panel_settings() });
      api.getPanel(SETTINGS_ID)?.api.setActive();
    } else if (!panelVisible.value.settings && existingSettings) {
      api.removePanel(existingSettings);
    }

    // The licences: a read, long and wide. Same route as the preferences.
    drawersRef.current.set(CREDITS_ID, (host) => render(<CreditsTab />, host));
    const existingCredits = api.getPanel(CREDITS_ID);
    if (panelVisible.value.credits && !existingCredits) {
      api.addPanel({ id: CREDITS_ID, component: CREDITS_ID, title: m.panel_credits() });
      api.getPanel(CREDITS_ID)?.api.setActive();
    } else if (!panelVisible.value.credits && existingCredits) {
      api.removePanel(existingCredits);
    }

    // Frame selection is a wide table doubled with a grid of charts: same reason as
    // preprocessing for putting it in the centre. It opens from the wizard's report, from the
    // activity bar, or through `app.layout.show('selector')`.
    drawersRef.current.set(SELECTOR_ID, (host) => render(<SelectorTab />, host));
    const existingSelector = api.getPanel(SELECTOR_ID);
    if (panelVisible.value.selector && !existingSelector) {
      api.addPanel({ id: SELECTOR_ID, component: SELECTOR_ID, title: m.panel_selector() });
      api.getPanel(SELECTOR_ID)?.api.setActive();
    } else if (!panelVisible.value.selector && existingSelector) {
      api.removePanel(existingSelector);
    }

    // The light curve is a wide chart: same reason for putting it in the centre. It reads the
    // last finished `LightCurve` job — the domain measures, the panel only shows the shape,
    // which no sorted column gives.
    drawersRef.current.set(LIGHTCURVE_ID, (host) => render(<LightCurveTab />, host));
    const existingCurve = api.getPanel(LIGHTCURVE_ID);
    if (panelVisible.value.lightcurve && !existingCurve) {
      api.addPanel({ id: LIGHTCURVE_ID, component: LIGHTCURVE_ID, title: m.panel_lightcurve() });
      api.getPanel(LIGHTCURVE_ID)?.api.setActive();
    } else if (!panelVisible.value.lightcurve && existingCurve) {
      api.removePanel(existingCurve);
    }

    // --- restoring a project, once every tab has been recreated -------------
    //
    // Last, and that is what counts: the reconciliation above activates *every* tab it adds,
    // so that the last one in the list would win the foreground.
    const active = takePendingActiveTab();
    if (active) api.getPanel(active)?.api.setActive();
  }, [
    windows.value,
    snapshot.value?.active_window,
    snapshot.value?.rev,
    rtpOwners.value,
    openScripts.value,
    openContainers.value,
    panelVisible.value.doc,
    panelVisible.value.home,
    panelVisible.value.pipeline,
    panelVisible.value.selector,
  ]);

  return <div ref={hostRef} style={{ height: '100%', width: '100%' }} />;
}

function titleFor(win: WindowState): string {
  const name = win.file_path ? win.file_path.split(/[\\/]/).pop() : win.id;
  return `${win.is_modified ? '● ' : ''}${name ?? win.id}`;
}

function titleForScript(doc: ScriptDoc): string {
  return `${doc.dirty ? '● ' : ''}${doc.title}`;
}
