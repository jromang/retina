// Resize handles of an undecorated window.
//
// # Why they exist
//
// tao handles `WM_NCHITTEST` correctly for an undecorated window, but WebView2 creates **child**
// HWNDs that cover the whole client area: the message does not reach the parent window
// and the edges are not grabbable. This is the classic problem of Tauri applications under
// Windows. So we redo the hit test in CSS and call `drag_resize_window` back through IPC.
//
// No `-webkit-app-region: drag`: that is an Electron extension, with no effect in WebView2.
// Writing it would give the illusion that it works.

import { inNativeShell } from './native';
import { windowMaximized, windowStartResize, type ResizeDir } from './titlebar/windowClient';

const DIRECTIONS: readonly ResizeDir[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'];

export function WindowResizeHandles() {
  // A maximized window cannot be resized, and the handles would eat the clicks at the
  // edge of the screen.
  if (!inNativeShell() || windowMaximized.value) return null;

  return (
    <>
      {DIRECTIONS.map((direction) => (
        <div
          key={direction}
          class="resize-handle"
          data-dir={direction}
          onPointerDown={(event) => {
            event.preventDefault();
            windowStartResize(direction);
          }}
        />
      ))}
    </>
  );
}
