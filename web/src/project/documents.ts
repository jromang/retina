// A project's documents blob — what the domain cannot know about.
//
// # Why these states live here, and travel in the project nonetheless
//
// Script tabs were placed **on the client side**, and that choice holds: an editing tab is
// chrome, not a domain action. Persisting them seems to contradict it — either the project
// format carries shell state, or scripts acquire a presence in the domain.
//
// There is nothing to arbitrate, because the mechanism already existed: **perspectives** work
// exactly this way. The server *asks* the client to serialize its layout, the client answers,
// and the opaque blob is written alongside the rest. A project asks for its open documents in
// the same way. The domain gains no notion of a tab, and console parity stays intact:
// `app.save_project` saves everything, `app.open_project` restores everything, including
// without a shell — in which case the blob is simply carried without being interpreted.
//
// # What is not restored, and what one needs to know
//
// The **Monaco undo stack**. A model recreated from its text has no history: reopening a
// project and pressing Ctrl+Z does not go back past the save. The content itself is intact,
// unsaved buffers included — which is the point.

import {
  restoreTranscript,
  serializeTranscript,
  type SerializedBlock,
} from '../console/transcript';
import { filesRoot, setFilesRoot } from '../panels/filesRoot';
import {
  restoreContainers,
  serializeContainers,
  type SerializedContainers,
} from '../pipeline/containerEdit';
import {
  restoreScripts,
  serializeScripts,
  type SerializedScripts,
} from '../scripts/scripts';

export const DOCUMENTS_VERSION = 1;

export interface DocumentsBlob {
  version: number;
  scripts: SerializedScripts;
  containers: SerializedContainers;
  /** Explorer root: reopening a project must reopen *its* working directory. */
  filesRoot: string | null;
  transcript: SerializedBlock[];
  /** Active center tab — see `takePendingActiveTab`, consumed by `CenterDock`. */
  activeTab: string | null;
}

/**
 * How to obtain the active center tab.
 *
 * Injected by `CenterDock` rather than imported: this module is pure computation, testable
 * without a DOM or dockview, and hard-wiring it here would make it unusable under vitest.
 *
 * # Why only the active tab, and not the dockview arrangement
 *
 * An `api.toJSON()` is easy to write; reading it back is not. `api.fromJSON()` **throws** when
 * it meets our panels (`Cannot read properties of undefined (reading '_isDisposed')` —
 * measured in e2e), because our components are created lazily from a table of renderers that
 * the reconstruction does not know about yet. And its failure is not neutral: it leaves the
 * layout half mutated, so that even setting the active tab afterwards no longer takes.
 *
 * The arrangement of the tabs is therefore **out of scope**, and the field does not exist in
 * the blob rather than sitting there never to be read back. What matters — which documents are
 * open, their content, and which one is in front — is restored.
 */
let dockProvider: (() => { activeTab: string | null }) | null = null;

export function setDockProvider(provider: (() => { activeTab: string | null }) | null): void {
  dockProvider = provider;
}

export function serializeDocuments(): DocumentsBlob {
  return {
    version: DOCUMENTS_VERSION,
    scripts: serializeScripts(),
    containers: serializeContainers(),
    filesRoot: filesRoot.value,
    transcript: serializeTranscript(),
    activeTab: dockProvider?.().activeTab ?? null,
  };
}

/** Tab to bring to the front once reconciliation is over. */
let pendingActive: string | null = null;

export function takePendingActiveTab(): string | null {
  const value = pendingActive;
  pendingActive = null;
  return value;
}

/**
 * Restores a project's documents. Returns `false` if the blob is not usable.
 *
 * The order is that of the dependencies: the explorer root and the transcript depend on
 * nothing, the scripts and recipes come next, and the active tab is set aside — setting it
 * right away would be pointless since the tabs do not exist yet on the dockview side, and the
 * last tab added would steal the front.
 *
 * An unknown version touches nothing rather than half-applying a format we do not understand:
 * the current session is worth more than a half-replaced one.
 */
export function restoreDocuments(blob: unknown): boolean {
  if (!isDocumentsBlob(blob)) {
    console.warn('[retina] unreadable project documents — ignored', blob);
    return false;
  }
  // **Before** touching the signals: setting `openScripts` triggers the dock reconciliation,
  // which consumes this value at the end of its pass. Filling it in afterwards means letting a
  // reconciliation through that finds it empty — the project's active tab was then lost, and
  // the last tab added kept the front.
  pendingActive = blob.activeTab ?? null;
  setFilesRoot(blob.filesRoot ?? null);
  restoreTranscript(blob.transcript ?? []);
  restoreScripts(blob.scripts);
  restoreContainers(blob.containers);
  return true;
}

function isDocumentsBlob(value: unknown): value is DocumentsBlob {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<DocumentsBlob>;
  if (candidate.version !== DOCUMENTS_VERSION) return false;
  return (
    typeof candidate.scripts === 'object' &&
    candidate.scripts !== null &&
    Array.isArray(candidate.scripts.docs) &&
    typeof candidate.containers === 'object' &&
    candidate.containers !== null &&
    Array.isArray(candidate.containers.docs)
  );
}
