// Protocol types — a hand-written mirror of python/retina/server/state.py.
//
// Written by hand rather than generated: the schema is small and stable, and a type-generation
// toolchain would be one more tool to maintain solo. The safety net is on the Python side
// (tests/server/test_rpc.py checks the shape actually emitted).

export interface StfChannel {
  shadows: number;
  midtones: number;
  highlights: number;
}

export interface ViewState {
  id: string;
  is_preview: boolean;
  width: number;
  height: number;
  channels: number;
  /** Changes as soon as the pixels change — serves as a URL version for /api/pixels. */
  pixel_gen: number;
  history: {
    labels: string[];
    index: number;
    can_undo: boolean;
    can_redo: boolean;
    /**
     * `process_id` of the step, or `null` for the initial state and for anything that is not
     * replayable. This is what lets the panel offer editing only where it will work: a pencil
     * that fails would be worse than no pencil at all.
     */
    processes: (string | null)[];
  };
  stf: { enabled: boolean; channels: StfChannel[] };
  /**
   * Summary of the properties attached to the view (measurements, notes) — **never** their
   * content: the measurements of a dense field run to hundreds of stars, and republishing them
   * with every snapshot would cost tens of KB per burst. `rev` says they changed; the data is
   * requested through `app.view_property`. Absent when the view carries none.
   */
  properties?: { rev: number; keys: string[] };
  /** Previews only: (x0, y0, x1, y1) in image coordinates. */
  rect?: [number, number, number, number];
  volatile?: boolean;
}

export interface MaskState {
  /** Whether the mask is honored by processes ("Enable Mask"). */
  enabled: boolean;
  inverted: boolean;
  width: number;
  height: number;
  channels: number;
  /** URL version for /api/mask/{window}.f16, like pixel_gen for the pixels. */
  gen: number;
}

/**
 * Vector overlay placed by the domain (`app.add_overlay`), in **image** coordinates.
 *
 * Mirrors the contract documented in `ViewportState.add_overlay`. The fields are optional
 * because the domain validates only the `kind`: a script may place an incomplete overlay, and
 * rendering must ignore it without breaking the rest of the layer.
 */
export type OverlayItem = {
  kind: 'markers' | 'lines' | 'text' | 'ellipses' | 'rects';
  /** Groups the overlays of a single tool, for selective clearing. */
  tag?: string;
  /** RGBA in 0..1 (the domain's convention, not CSS's). */
  color?: readonly number[];
  size?: number;
  width?: number;
  /** `markers`, and `lines` as a single polyline. */
  points?: ReadonlyArray<readonly [number, number]>;
  /** `lines`: several independent polylines. */
  segments?: ReadonlyArray<ReadonlyArray<readonly [number, number]>>;
  /** `rects`: (x0, y0, x1, y1). */
  rects?: ReadonlyArray<readonly [number, number, number, number]>;
  /** `rects`: rotation in degrees about the center. */
  angle?: number;
  /** `text`: `{x, y, text}`; `ellipses`: `{x, y, rx, ry, theta}` (theta in radians). */
  items?: ReadonlyArray<Record<string, number | string>>;
};

export interface ViewportState {
  zoom: number;
  center: [number, number];
  channel: string;
  stf_enabled: boolean;
  interaction_mode: string;
  mask_display_mode: string;
  /** Whether the mask is *displayed* ("Show Mask") — distinct from MaskState.enabled. */
  mask_visible: boolean;
  transparency_mode: string;
  overlays: OverlayItem[];
  readout: {
    probe_size: number;
    color_space: string;
    real: boolean;
    precision: number;
    show_loupe: boolean;
  };
}

export interface WindowState {
  id: string;
  file_path: string | null;
  is_modified: boolean;
  width: number;
  height: number;
  channels: number;
  keyword_count: number;
  has_wcs: boolean;
  current_view: string;
  mask: MaskState | null;
  views: ViewState[];
  viewport: ViewportState;
}

/** An in-flight job, as the snapshot describes it (`JobRunner.active`). */
export interface JobSnapshot {
  id: string;
  process_id: string;
  view: string | null;
  state: 'queued' | 'running' | 'done' | 'error' | 'cancelled';
  /** final message (error) — empty while the job runs */
  message: string;
  /** progress, `null` if the process is not instrumented */
  fraction: number | null;
  /** label of the current step ("Measuring 12/40") */
  progress_message: string;
  /**
   * Output of a **measurement** process (`DynamicPSF`, `Statistics`…), which does not touch the
   * pixels and therefore has nothing else to return. Travels through the `job.done`
   * notification; snapshots list only *in-flight* jobs, so a reconnection loses it — in which
   * case the measurement is run again.
   */
  result?: Record<string, unknown> | null;
}

/** An entry in the notification center (`app.notifications`), shared domain state. */
export interface NotificationState {
  id: string;
  kind: 'info' | 'warning' | 'error';
  message: string;
  source: string;
  timestamp: number;
}

export interface Snapshot {
  rev: number;
  active_window: string | null;
  active_view: string | null;
  windows: WindowState[];
  layout: { open_processes: string[]; locked: boolean; panels: string[] };
  /** Jobs still in flight. Without this key, reconnecting mid-run
   *  lost the progress bar and its Cancel button. */
  jobs: JobSnapshot[];
  /** The whole notification center (bounded on the domain side): this is what repairs the
   *  bell after a reconnection, just as `jobs` repairs the progress bar. */
  notifications: NotificationState[];
  /** Windows whose cameras are synchronized. Derived from the domain — the link can also be
   *  set from the console, and two clients must see the same state. */
  linked_viewports: string[];
  /** Path of the current project, or `null`. The title bar names it. */
  project: string | null;
}

/** What the server knows of the user session — recents, reopening, current project. */
export interface SessionState {
  recent_files: string[];
  recent_projects: string[];
  reopen: boolean;
  has_autosession: boolean;
  project: string | null;
  /**
   * Explicit language choice (`'en' | 'fr'`), or `null` for "follow the system".
   * Distinct from `effective_language`: this is what the menu checks, not what is displayed.
   */
  language: string | null;
  /** Language actually served by the server — the authority, cf. `shell/locale.ts`. */
  effective_language: string;
  /** Documents of a project opened **without** a client: nobody was there to receive them. */
  documents?: unknown;
}

/** A process parameter — the frontend derives its form field from it. */
export interface ParameterMeta {
  id: string;
  /** real | int | str | enum | bool | path | pathlist | floatlist | intlist | text | points | pointlist */
  type: string;
  default: unknown;
  min: number | null;
  max: number | null;
  choices: string[] | null;
  label: string;
  tooltip: string;
  /**
   * Conditional visibility: the field is shown only if the parameter `param` (another field of
   * the same form) holds one of `values`. `null`/absent = always visible. This is a display
   * convenience — the value is still sent at execution time, hidden or not.
   */
  visible_when?: { param: string; values: unknown[] } | null;
}

export interface ProcessMeta {
  process_id: string;
  category: string;
  is_global: boolean;
  is_maskable: boolean;
  creates_window: boolean;
  supports_realtime: boolean;
  has_doc: boolean;
  /** Tabler icon name, resolved through /api/icons later on. */
  icon: string;
  parameters: ParameterMeta[];
}

export interface LayoutState {
  visible: Record<string, boolean>;
  /** Informational: the client re-derives the zones from `visible`, it does not store them. */
  zones?: Record<string, boolean>;
  locked: boolean;
  open_processes: string[];
}

export interface Hello {
  protocol: number;
  /** Identity of this connection — used to recognize its own viewport echoes. */
  connection: string | null;
  /** Server process identifier: confines pixel URLs to this run. */
  run: string;
  snapshot: Snapshot;
  /** Server-side layout — the client adopts it, it does not overwrite it. */
  layout: LayoutState;
  /** Session: recents, reopening, current project, documents to restore where applicable. */
  session: SessionState;
  methods: string[];
  /** File extensions by group, from the domain's dispatch point — see {@link ImageFormats}. */
  formats?: ImageFormats;
}

/**
 * Extensions the domain reads and writes, without the leading dot.
 *
 * Published by the server rather than mirrored here: a list of our own would drift at the
 * first format added. `byte_raster` is the one that carries a warning — those formats
 * quantize, so a linear image written into one of them comes out black.
 */
export interface ImageFormats {
  astro: string[];
  float_raster: string[];
  byte_raster: string[];
  /** Camera RAW — read only: rawpy demosaics, it does not write back. */
  raw: string[];
}

/** `project.command` notification — same shape as `layout.command`. */
export interface ProjectCommand {
  op: 'request_documents' | 'restore_documents';
  /** Correlation token for a document request: to be echoed back verbatim. */
  request?: string;
  documents?: unknown;
}

/** `viewport.changed` notification — outside the snapshot, too frequent to trigger one. */
export interface ViewportChanged {
  window: string;
  viewport: ViewportState;
  /** Connection the gesture originated from; `null` = console or script. */
  origin: string | null;
}

export interface EchoEvent {
  code: string;
}
