// Python highlighting for the transcript, without instantiating an editor.
//
// `monaco.editor.colorize` tokenizes a string and returns escaped HTML carrying the `.mtk*`
// classes that the theme service injects globally into the document. A transcript entry is
// therefore highlighted exactly like the prompt just below it, without the cost of one editor
// per line — a transcript holds hundreds of them.
//
// Since Monaco arrives through a dynamic import (~2.5 MB), everything here must tolerate its
// absence: the console opens and is used before it is loaded, and returning plain text in the
// meantime is better than delaying the display.

type MonacoApi = typeof import('monaco-editor');

let api: MonacoApi | null = null;

/** Tokenization cache: the same block is re-rendered on every change of the signal. */
const cache = new Map<string, string>();
const CACHE_LIMIT = 500;

/**
 * Hands over the Monaco API once loaded. Called by the panel, which drives the dynamic import —
 * this module imports nothing itself, otherwise it would pull Monaco into the initial bundle.
 */
export function registerMonaco(monaco: MonacoApi): void {
  api = monaco;
}

/** True when `colorizePython` can return something other than `null`. */
export function highlightReady(): boolean {
  return api !== null;
}

/**
 * Highlighted HTML for the code, or `null` if Monaco is not there yet (the caller renders text).
 *
 * The result is HTML **escaped by Monaco**: that is what authorizes the
 * `dangerouslySetInnerHTML` on the rendering side. Never concatenate unescaped text into it.
 */
export function colorizePython(text: string): Promise<string> | null {
  if (!api) return null;
  const hit = cache.get(text);
  if (hit !== undefined) return Promise.resolve(hit);
  // `colorize` preserves line endings; the container is `pre-wrap`, so nothing is touched up.
  return api.editor.colorize(text, 'python', {}).then((html) => {
    if (cache.size >= CACHE_LIMIT) cache.clear();
    cache.set(text, html);
    return html;
  });
}
