// The zone contract — the part that can be checked without a browser.
//
// Zones are *derived* from panels, on both sides of the network. Two independent derivations
// that must reach the same state: exactly the kind of agreement that silently comes apart when
// someone adds a panel and forgets to file it under a zone.

import { describe, expect, it } from 'vitest';

import {
  BOTTOM_PANELS,
  BUILTIN_PERSPECTIVES,
  DEFAULT_VISIBLE,
  PANELS,
  PANEL_META,
  PERSPECTIVE_LAYOUTS,
  RIGHT_PANELS,
  SIDEBAR_PANELS,
  ZONE_META,
  ZONE_PANELS,
  ZONES,
  type PanelId,
} from '../src/shell/panels';

describe('zones', () => {
  it('covers every zone with metadata', () => {
    expect(Object.keys(ZONE_META).sort()).toEqual([...ZONES].sort());
    for (const zone of ZONES) {
      expect(ZONE_META[zone].icon).toBeTruthy();
      // The "collapsed" icon is a different one: VS Code changes the glyph, not just its color.
      expect(ZONE_META[zone].iconOff).not.toBe(ZONE_META[zone].icon);
    }
  });

  it('reuses exactly the existing panel groups', () => {
    expect(ZONE_PANELS.sidebar).toBe(SIDEBAR_PANELS);
    expect(ZONE_PANELS.bottom).toBe(BOTTOM_PANELS);
    expect(ZONE_PANELS.right).toBe(RIGHT_PANELS);
  });

  it('files no panel under two zones', () => {
    const seen = new Set<PanelId>();
    for (const zone of ZONES) {
      for (const panel of ZONE_PANELS[zone]) {
        expect(seen.has(panel), `${panel} belongs to two zones`).toBe(false);
        seen.add(panel);
      }
    }
  });

  it('names only known panels', () => {
    for (const zone of ZONES) {
      for (const panel of ZONE_PANELS[zone]) {
        expect(PANELS).toContain(panel);
      }
    }
  });

  it('leaves the center dock panels out of any zone', () => {
    // `doc`, `home` and `desktop` live in the CenterDock: filing them under a zone would make
    // them collapsible by an icon that has nothing to do with them.
    const zoned = ZONES.flatMap((zone) => [...ZONE_PANELS[zone]]);
    expect(zoned).not.toContain('doc');
    expect(zoned).not.toContain('home');
    expect(zoned).not.toContain('desktop');
  });
});

describe('panels', () => {
  it('gives every panel its metadata and its initial visibility', () => {
    // The failure mode of a newly added panel: one of the four tables forgotten. The activity
    // bar then renders an empty icon, or the perspective no longer compiles.
    for (const panel of PANELS) {
      expect(PANEL_META[panel]?.title, `missing metadata: ${panel}`).toBeTruthy();
      expect(DEFAULT_VISIBLE[panel], `missing visibility: ${panel}`).toBeDefined();
    }
  });

  it('covers every panel in each built-in perspective', () => {
    for (const name of BUILTIN_PERSPECTIVES) {
      for (const panel of PANELS) {
        expect(PERSPECTIVE_LAYOUTS[name][panel], `${name} ignores ${panel}`).toBeDefined();
      }
    }
  });

  it('opens only one sidebar panel per perspective', () => {
    // The sidebar is exclusive: a second panel set to `true` would not open anything extra, it
    // would simply be ignored. That is the kind of dead setting a preset accumulates without
    // anyone noticing — the test found one on "Script".
    for (const name of BUILTIN_PERSPECTIVES) {
      const sidebarOpen = SIDEBAR_PANELS.filter((panel) => PERSPECTIVE_LAYOUTS[name][panel]);
      expect(sidebarOpen.length, `${name} opens ${sidebarOpen.join(' and ')}`).toBeLessThanOrEqual(
        1,
      );
    }
  });

  it('shows the server disk and the console in the Script perspective', () => {
    expect(PERSPECTIVE_LAYOUTS.Script.files).toBe(true);
    expect(PERSPECTIVE_LAYOUTS.Script.console).toBe(true);
  });
});
