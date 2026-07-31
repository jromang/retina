// Monaco setup: minimal imports, theme wired to our tokens, server-side completion.
//
// We do **not** import `monaco-editor` in full (~5 MB, every language, every worker) but only
// the core, Python syntax highlighting and the contributions a console *and* a script editor
// need. The rest — diff, TypeScript IntelliSense — would be dead weight.
//
// The second block of imports is what the full-page editor adds to the console: without
// `findController` there is no Ctrl+F, without `folding` no code folding, and without `hover`
// and `parameterHints` the providers registered below would never appear — they would be
// called into the void, which is Monaco's most confusing failure mode.
//
// Completion does not come from Monaco but from the server: IPython is the one querying the
// **live** objects (`app.active_view` is a View, not an inferred type). No static analyzer can
// do that, and that is exactly the point of a console attached to the state.

import * as monaco from 'monaco-editor/editor/editor.api';
// 0.56 moved the per-language entry points under `languages/definitions/`; the old
// `basic-languages/<lang>/<lang>.contribution` is gone and its replacement pulls all ~90
// languages at once. This one still registers Python alone, tokenizer lazily loaded.
import 'monaco-editor/languages/definitions/python/register';
import 'monaco-editor/editor/contrib/suggest/browser/suggestController';
import 'monaco-editor/editor/contrib/bracketMatching/browser/bracketMatching';
import 'monaco-editor/editor/contrib/wordOperations/browser/wordOperations';
import 'monaco-editor/editor/contrib/comment/browser/comment';
import 'monaco-editor/editor/contrib/find/browser/findController';
import 'monaco-editor/editor/contrib/folding/browser/folding';
import 'monaco-editor/editor/contrib/hover/browser/hoverContribution';
import 'monaco-editor/editor/contrib/parameterHints/browser/parameterHints';
import 'monaco-editor/editor/contrib/multicursor/browser/multicursor';
import 'monaco-editor/editor/contrib/linesOperations/browser/linesOperations';
import 'monaco-editor/editor/contrib/smartSelect/browser/smartSelect';
import 'monaco-editor/editor/contrib/indentation/browser/indentation';
import 'monaco-editor/editor/contrib/contextmenu/browser/contextmenu';
import 'monaco-editor/editor/contrib/clipboard/browser/clipboard';
import 'monaco-editor/editor/contrib/gotoError/browser/gotoError';
import 'monaco-editor/editor/contrib/wordHighlighter/browser/wordHighlighter';
import 'monaco-editor/editor/standalone/browser/quickAccess/standaloneGotoLineQuickAccess';
import EditorWorker from 'monaco-editor/editor/editor.worker?worker';

import { client } from '../api/client';
import { callContext, inspectAt, splitParameters } from './inspect';

let configured = false;

interface CompletionResponse {
  matches: string[];
  replace_start: number;
  replace_end: number;
}


/** Theme derived from the same CSS variables as the rest of the shell.
 *
 * Monaco wants exactly six hex digits and throws `Illegal value for token color` otherwise.
 * The variables are written `#cccccc` in `styles/tokens.css`, but what is read here is the
 * *computed* value, and a CSS minifier is free to shorten it to `#ccc` -- Vite 8's does. So
 * expand the shorthand rather than trusting the stylesheet to survive the build.
 */
function readToken(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const hex = (value || fallback).replace('#', '');
  return /^[0-9a-fA-F]{3}$/.test(hex)
    ? hex.split('').map((digit) => digit + digit).join('')
    : hex;
}

export function setupMonaco(): typeof monaco {
  if (configured) return monaco;
  configured = true;

  // A single worker: with no language to analyze statically, the editor worker is enough.
  self.MonacoEnvironment = {
    getWorker: () => new EditorWorker(),
  };

  monaco.editor.defineTheme('retina-dark', {
    base: 'vs-dark',
    inherit: true,
    // The token colors come from the same CSS variables as the rest of the shell. They repeat
    // the vs-dark values, which we already inherit: the appearance does not change, but the
    // highlighting becomes adjustable by rewriting `:root` — which is what a light theme will
    // do.
    //
    // These rules also serve outside the editor: `monaco.editor.colorize` (the console
    // transcript) emits the `.mtk*` classes that the theme service derives from here.
    rules: [
      { token: 'keyword', foreground: readToken('--retina-syntax-keyword', '#569cd6') },
      { token: 'string', foreground: readToken('--retina-syntax-string', '#ce9178') },
      { token: 'number', foreground: readToken('--retina-syntax-number', '#b5cea8') },
      { token: 'comment', foreground: readToken('--retina-syntax-comment', '#6a9955') },
      { token: 'type', foreground: readToken('--retina-syntax-type', '#4ec9b0') },
      { token: 'delimiter', foreground: readToken('--retina-syntax-delimiter', '#dcdcdc') },
    ],
    colors: {
      'editor.background': `#${readToken('--vscode-input-background', '#3c3c3c')}`,
      'editor.foreground': `#${readToken('--vscode-input-foreground', '#cccccc')}`,
      'editorCursor.foreground': `#${readToken('--vscode-foreground', '#cccccc')}`,
      'editor.lineHighlightBackground': '#00000000',
    },
  });

  monaco.languages.registerCompletionItemProvider('python', {
    // `.` also triggers completion: it is the most frequent gesture on `app.`
    triggerCharacters: ['.'],
    async provideCompletionItems(model, position) {
      const code = model.getValue();
      const offset = model.getOffsetAt(position);
      let response: CompletionResponse;
      try {
        response = await client.call<CompletionResponse>('console.complete', {
          code,
          cursor_pos: offset,
        });
      } catch {
        return { suggestions: [] };
      }

      // The server returns a range in offsets; Monaco reasons in (line, column).
      const start = model.getPositionAt(response.replace_start);
      const end = model.getPositionAt(response.replace_end);
      const range = {
        startLineNumber: start.lineNumber,
        startColumn: start.column,
        endLineNumber: end.lineNumber,
        endColumn: end.column,
      };

      return {
        suggestions: response.matches.map((match) => ({
          label: match,
          kind: monaco.languages.CompletionItemKind.Variable,
          insertText: match,
          range,
        })),
      };
    },
  });

  // Hover: IPython's `?`, on the live object. The block returned by the server is already
  // formatted for reading (Signature / Docstring / File / Type) — we drop it into a code block
  // rather than trying to turn it back into Markdown, which would break on the first docstring
  // containing an asterisk or an underscore.
  monaco.languages.registerHoverProvider('python', {
    async provideHover(model, position) {
      const word = model.getWordAtPosition(position);
      if (!word) return null;
      const info = await inspectAt(model.getValue(), model.getOffsetAt(position));
      if (!info?.found || !info.text.trim()) return null;
      return {
        range: {
          startLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endLineNumber: position.lineNumber,
          endColumn: word.endColumn,
        },
        contents: [{ value: '```text\n' + info.text.trimEnd() + '\n```' }],
      };
    },
  });

  // Signature help: Shift+Tab, and automatically after `(` or `,`.
  monaco.languages.registerSignatureHelpProvider('python', {
    signatureHelpTriggerCharacters: ['(', ','],
    async provideSignatureHelp(model, position) {
      const code = model.getValue();
      const context = callContext(code, model.getOffsetAt(position));
      if (!context) return null;
      // We query the position of the **callee name**, not that of the cursor: `_symbol_at` on
      // the server side expands around the offset it receives, and inside the parentheses it
      // would find only the argument being typed.
      const info = await inspectAt(code, context.calleeEnd);
      const definition = info?.init_definition ?? info?.definition;
      if (!definition) return null;
      return {
        value: {
          signatures: [
            {
              label: definition.trim(),
              parameters: splitParameters(definition).map((label) => ({ label })),
              ...(info?.docstring ? { documentation: info.docstring } : {}),
            },
          ],
          activeSignature: 0,
          activeParameter: context.activeParameter,
        },
        dispose: () => undefined,
      };
    },
  });

  return monaco;
}

export type { monaco };
