// Active dynamic tool: the channel through which a click on the viewport reaches a panel.
//
// # Why this lives on the client side, and not in the domain
//
// Placing a DBE sample point, an alignment pair or a clone stamp means **filling in an instance
// parameter** before launching the process. The console equivalent is not some `app.*` to be
// invented, it is `DynamicBackgroundExtraction(samples=[(x, y)]).execute_on(view)`.
// The GUI gesture therefore only fills the form; the only mutation leaves through the RPC
// `process.run`, which is echoed like any other process. Giving the domain a notion of
// "pending points" would duplicate the form's values and would make it carry state that
// belongs to the chrome alone — exactly what was refused for the script tabs.
//
// # What the domain keeps
//
// `ViewportState.interaction_mode` stays in charge of **what a click does**: a panel that
// activates sets `app.set_interaction_mode('dynamic')`, and a `set_interaction_mode('pan')` typed
// in the console is enough to disarm the tool. The signal below only says *which* tool listens.

import { signal } from '@preact/signals';

import type { Camera } from './camera';

export interface DynamicToolEvent {
  /** Window under the pointer — not necessarily the active one: DynamicAlignment works on two. */
  windowId: string;
  /** View under the pointer (finest preview, as for a drop). */
  viewId: string;
  /** Point in **image** coordinates. */
  point: readonly [number, number];
  event: PointerEvent;
}

export interface DynamicTool {
  /** Identifier of the owning panel — used for diagnostics and for the status indicator. */
  id: string;
  /** Label shown in the viewport toolbar while the tool is armed. */
  label: string;
  /** CSS cursor while the tool is active. */
  cursor?: string;
  onDown?(event: DynamicToolEvent): void;
  onMove?(event: DynamicToolEvent): void;
  onUp?(event: DynamicToolEvent): void;
  /**
   * Transient drawing, called on every frame on the 2D layer of the viewport of `windowId`.
   *
   * Used for what changes too fast for a server round trip: crop handles, the stamp's radius
   * circle, the source→destination line. What is *committed*, on the other hand, goes out as a
   * domain overlay — visible from the console too.
   */
  chrome?(ctx: CanvasRenderingContext2D, camera: Camera, windowId: string): void;
}

/** The armed tool, or `null`. One at a time: two panels would fight over the clicks. */
export const dynamicTool = signal<DynamicTool | null>(null);

/**
 * Arms a tool and returns the disarm function.
 *
 * Disarming removes only *this* tool: if another panel has armed itself in the meantime,
 * unmounting the first must not silence it — without this guard, closing a panel would
 * silently deactivate the one that has just been opened.
 */
export function armDynamicTool(tool: DynamicTool): () => void {
  dynamicTool.value = tool;
  return () => {
    if (dynamicTool.value?.id === tool.id) dynamicTool.value = null;
  };
}
