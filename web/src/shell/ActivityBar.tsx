// Activity bar — the main navigation, VS Code style.
//
// Every click goes through `app.layout.activate(...)` / `toggle(...)` as an RPC, never through a
// local mutation: that is what makes `app.layout.activate('windows')` appear in the
// console. The `layout.command` sent back by the server then applies the state — the loop is
// deliberately complete rather than short-circuited.

import { m } from '../paraglide/messages';
import { activeSidebarPanel, panelVisible, requestActivate, requestToggle } from './layoutClient';
import { BOTTOM_PANELS, PANEL_META, SIDEBAR_PANELS, type PanelId } from './panels';
import { windows } from '../state/store';

interface ItemProps {
  panel: PanelId;
  active: boolean;
  badge?: number;
  onClick: () => void;
}

function Item({ panel, active, badge, onClick }: ItemProps) {
  const meta = PANEL_META[panel];
  const title = meta.hint ? `${meta.title} (${meta.hint})` : meta.title;
  return (
    <button
      class="activity-item"
      // Stable landmark for the guided tour: it must be able to point at a specific button
      // without depending on the order of the icons nor on their translated label.
      data-activity={panel}
      aria-current={active}
      title={title}
      onClick={onClick}
    >
      <i class={`codicon codicon-${meta.icon}`} aria-hidden="true" />
      {badge !== undefined && badge > 0 && <span class="activity-badge">{badge}</span>}
    </button>
  );
}

export function ActivityBar() {
  const active = activeSidebarPanel.value;
  const windowCount = windows.value.length;

  return (
    <nav class="activity-bar" aria-label={m.activity_bar_label()}>
      {SIDEBAR_PANELS.map((panel) => (
        <Item
          key={panel}
          panel={panel}
          active={active === panel}
          {...(panel === 'windows' ? { badge: windowCount } : {})}
          onClick={() => requestActivate(panel)}
        />
      ))}
      {/* Preprocessing is not a sidebar panel but a central tab;
          it still belongs here, below the others: it is the starting point of a
          session, and the activity bar is the interface's only permanent landmark. */}
      <Item
        panel="pipeline"
        active={panelVisible.value.pipeline}
        onClick={() => requestToggle('pipeline')}
      />
      {/* Same status as preprocessing: a central tab, but a permanent entry point.
          Sorting one's frames is the gesture that immediately follows a preprocessing run, and the
          second one a session starts with. */}
      <Item
        panel="selector"
        active={panelVisible.value.selector}
        onClick={() => requestToggle('selector')}
      />
      <div style={{ flex: 1 }} />
      {BOTTOM_PANELS.map((panel) => (
        <Item
          key={panel}
          panel={panel}
          active={panelVisible.value[panel]}
          onClick={() => requestToggle(panel)}
        />
      ))}
      <Item
        panel="stf"
        active={panelVisible.value.stf}
        onClick={() => requestToggle('stf')}
      />
    </nav>
  );
}
