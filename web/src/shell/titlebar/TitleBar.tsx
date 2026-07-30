// VS Code-style title bar: logo · menus · command center · toggles · window buttons.
//
// It replaces the system title bar (the native window is created without decorations),
// hence the dragging and the double click handled by hand. In browser mode it stays — menus and
// command center are **application** chrome, not window chrome — minus the window chrome
// alone. That is also what makes the whole thing testable in Playwright, which necessarily runs
// outside the native shell.

import { useEffect, useState } from 'preact/hooks';

import { client } from '../../api/client';
import { connection } from '../../state/store';
import { CommandCenter } from './CommandCenter';
import { MenuBar } from './MenuBar';
import { WindowControls } from './WindowControls';
import { ZoneToggles } from './ZoneToggles';
import { windowDrag, windowToggleMaximize } from './windowClient';

interface Props {
  /** True in the native window — the only case where window chrome makes sense. */
  native: boolean;
}

/** The drag only starts from the bar's background, never from a button. */
function isDragSurface(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.dataset['drag'] === 'true';
}

export function TitleBar({ native }: Props) {
  const [perspectives, setPerspectives] = useState<string[]>([]);

  // User perspectives are menu entries: they are read back on every (re)connection,
  // since a script may have saved some in the meantime.
  useEffect(() => {
    if (connection.value !== 'open') return;
    void client
      .call<string[]>('layout.perspectives')
      .then(setPerspectives)
      .catch(() => undefined);
  }, [connection.value]);

  // `mousedown` and not `pointerdown`: `detail` — the click counter — is **0** on a
  // `pointerdown`. The guard below would therefore always be false there and the drag would
  // never start. It exists so as not to swallow the second click of a double click, which maximizes.
  const onMouseDown = (event: MouseEvent) => {
    if (!native || event.button !== 0 || event.detail !== 1) return;
    if (isDragSurface(event.target)) windowDrag();
  };

  const onDblClick = (event: MouseEvent) => {
    if (native && isDragSurface(event.target)) windowToggleMaximize();
  };

  return (
    <header
      class="title-bar"
      data-drag="true"
      onMouseDown={onMouseDown}
      onDblClick={onDblClick}
    >
      <img class="title-logo" src="/favicon.png" alt="" aria-hidden="true" />
      <MenuBar perspectives={perspectives} />
      <span class="title-drag" data-drag="true" />
      <CommandCenter />
      <span class="title-drag" data-drag="true" />
      <ZoneToggles />
      {native && <WindowControls />}
    </header>
  );
}
