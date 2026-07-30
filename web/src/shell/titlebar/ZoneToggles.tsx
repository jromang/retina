// The three layout toggles, to the right of the title bar.
//
// They collapse/expand **zones**, not panels: it is `app.layout.toggle_zone` that
// gets called, hence with a Python echo, and it is the server that remembers which panel to
// reopen (see `_zone_memory` in server/layout_backend.py). Do not reimplement that memory here.

import { requestToggleZone, zoneVisible } from '../layoutClient';
import { ZONE_META, ZONES } from '../panels';

export function ZoneToggles() {
  const visible = zoneVisible.value;

  return (
    <div class="title-actions">
      {ZONES.map((zone) => {
        const meta = ZONE_META[zone];
        const open = visible[zone];
        return (
          <button
            key={zone}
            type="button"
            class="title-action"
            data-zone={zone}
            data-open={open}
            aria-pressed={open}
            title={`${meta.title} (${meta.hint})`}
            onClick={() => requestToggleZone(zone)}
          >
            <i class={`codicon codicon-${open ? meta.icon : meta.iconOff}`} aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}
