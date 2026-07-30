// Script editing tab — full-page Monaco.
//
// # What this tab is not
//
// It is not a second console. Execution goes through `transcript.execute()`, hence through the
// **same** `console.execute` and the same IPython interpreter: the output is interleaved into
// the transcript, so is the echo of the GUI actions, and the state is shared. A script run here
// leaves its variables available at the prompt, which is the whole point of an editor attached
// to a live session rather than a subprocess launcher.
//
// # The Monaco model outlives the tab
//
// dockview destroys and recreates the element when a tab is moved; a model recreated on
// remounting would lose its undo stack. The models therefore live in a module-level registry,
// keyed by script id, and are disposed of only when the document is closed.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { busy, interrupt, lastExecutionError } from '../console/transcript';
import {
  activeScriptId,
  checkDisk,
  diskConflicts,
  keepMyVersion,
  openScripts,
  reloadFromDisk,
  reloadedScript,
  runFile,
  runInConsole,
  runnableSelection,
  saveScript,
  scriptCursor,
  scriptText,
  setScriptCursor,
  setScriptText,
} from './scripts';
import { editorLine, parseTraceback } from './traceback';

type Monaco = typeof import('monaco-editor');
type TextModel = import('monaco-editor').editor.ITextModel;

const models = new Map<string, TextModel>();

/** Owner of the error markers — Monaco replaces them wholesale, per owner. */
const MARKER_OWNER = 'retina-script';

// A closed document takes its model with it: without this, opening a hundred scripts in a
// session would leave a hundred buffers in Monaco.
openScripts.subscribe((docs) => {
  const alive = new Set(docs.map((doc) => doc.id));
  for (const [id, model] of models) {
    if (alive.has(id)) continue;
    model.dispose();
    models.delete(id);
  }
});

function modelFor(monaco: Monaco, id: string): TextModel {
  const existing = models.get(id);
  if (existing) return existing;
  const model = monaco.editor.createModel(scriptText(id), 'python');
  models.set(id, model);
  return model;
}

export function ScriptTab({ id }: { id: string }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<import('monaco-editor').editor.IStandaloneCodeEditor | null>(null);
  const [position, setPosition] = useState({ lineNumber: 1, column: 1 });
  const [notice, setNotice] = useState<string | null>(null);
  const doc = openScripts.value.find((entry) => entry.id === id);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    const cleanups: (() => void)[] = [];

    void import('../console/monaco').then(({ setupMonaco }) => {
      if (disposed) return;
      const monaco = setupMonaco();
      const editor = monaco.editor.create(host, {
        model: modelFor(monaco, id),
        theme: 'retina-dark',
        automaticLayout: true,
        fontFamily: 'var(--retina-font-mono)',
        fontSize: 13,
        minimap: { enabled: true },
        scrollBeyondLastLine: false,
        renderWhitespace: 'selection',
        tabSize: 4,
        insertSpaces: true,
      });
      editorRef.current = editor;

      cleanups.push(
        editor.onDidChangeModelContent(() => setScriptText(id, editor.getValue())).dispose,
      );
      cleanups.push(
        editor.onDidChangeCursorPosition((event) => {
          setPosition(event.position);
          // Also into the module: that is what a project saves. Outside the signal, hence
          // without redrawing the tabs on every arrow key.
          setScriptCursor(id, {
            lineNumber: event.position.lineNumber,
            column: event.position.column,
          });
        }).dispose,
      );

      // Cursor restored by a project: put it back, and bring it on screen. Without the
      // `reveal`, a cursor at line 400 would be correctly placed but invisible.
      const restored = scriptCursor(id);
      if (restored) {
        editor.setPosition(restored);
        editor.revealPositionInCenterIfOutsideViewport(restored);
      }
      cleanups.push(editor.onDidFocusEditorText(() => (activeScriptId.value = id)).dispose);

      // These three shortcuts are placed **inside** Monaco, not on `window`: the editor
      // consumes them (F5 therefore does not reload the page and never reaches the global
      // "apply the last process" shortcut), and they work whatever the state of the rest of
      // the shell.
      //
      // The context key is not decorative: `addCommand` registers in Monaco's **global**
      // service, shared by all editors. Without it, the console prompt's Enter applied here —
      // one could no longer create a line in a script — and conversely F5 would have executed
      // this buffer from the console.
      editor.createContextKey('retinaScriptEditor', true);
      const ICI = 'retinaScriptEditor';
      editor.addCommand(monaco.KeyCode.F5, () => run(editor.getValue()), ICI);
      editor.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.Enter, () => runSelection(), ICI);
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
        void saveScript(id);
      }, ICI);

      editor.focus();
    });

    return () => {
      disposed = true;
      for (const dispose of cleanups) dispose();
      // The model, by contrast, survives: it is disposed of when the document is closed.
      editorRef.current?.dispose();
      editorRef.current = null;
    };
  }, [id]);

  /**
   * Runs code and reports a refusal.
   *
   * Without this return value, F5 during an execution did **nothing, and said nothing**: the
   * worst of both worlds, since "refused" could not be told apart from "started but silent".
   */
  function run(code: string, lineOffset = 0): void {
    const started = runInConsole(code, { scriptId: id, lineOffset });
    setNotice(started ? null : m.script_already_running());
  }

  function runSelection(): void {
    const editor = editorRef.current;
    if (!editor) return;
    const selection = editor.getSelection();
    const selected = selection ? (editor.getModel()?.getValueInRange(selection) ?? '') : '';
    const line = selection?.positionLineNumber ?? 1;
    // The fragment sent starts at the first line of the selection (or at the cursor line if
    // nothing is selected): without this offset, a traceback would mark the top of the file.
    const first = selected.trim() ? (selection?.startLineNumber ?? line) : line;
    run(runnableSelection(editor.getValue(), selected, line), first - 1);
  }

  // Confront the buffer with its file — at the only two moments that matter (doctrine at the
  // head of `handlers_fs.py`: no watcher on the server side).
  //
  // The `IntersectionObserver` is what captures "I am coming back to my tab" without depending
  // on dockview's API: an inactive panel stays mounted but is not visible, and the observer
  // fires both on the first appearance and on the return. The window `focus` covers the other
  // half of the gesture — editing elsewhere, then coming back to Retina.
  useEffect(() => {
    const host = hostRef.current;
    const check = () => {
      void checkDisk(id).catch((error: unknown) => console.error('fs.stat', error));
    };
    globalThis.addEventListener('focus', check);
    const observer =
      host && typeof IntersectionObserver !== 'undefined'
        ? new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting)) check();
          })
        : null;
    if (observer && host) observer.observe(host);
    // Without an observer (an environment lacking the intersection API), the check on mount
    // remains: better once than never.
    else check();
    return () => {
      globalThis.removeEventListener('focus', check);
      observer?.disconnect();
    };
  }, [id]);

  // A silent reload replaced the buffer: the Monaco model must follow, otherwise the editor
  // would keep displaying — and re-saving — the stale text.
  useEffect(() => {
    const event = reloadedScript.value;
    if (!event || event.id !== id) return;
    const model = models.get(id);
    if (!model || model.getValue() === scriptText(id)) return;
    const editor = editorRef.current;
    const position = editor?.getPosition() ?? null;
    model.setValue(scriptText(id));
    // The position is put back as-is: the file changed, but staying at line 1 after a reload
    // would lose the place one was looking at. Monaco itself clamps a line that has fallen
    // outside the document.
    if (position) editor?.setPosition(position);
  }, [reloadedScript.value, id]);

  // The offending line, marked in the gutter and brought on screen. The reference
  // implementation does print `…, line N` in its console, but nothing there leads back to the
  // editor: this is a place where getting ahead costs one regular expression.
  useEffect(() => {
    const failure = lastExecutionError.value;
    const editor = editorRef.current;
    const model = models.get(id);
    if (!editor || !model) return;
    void import('../console/monaco').then(({ setupMonaco }) => {
      const monaco = setupMonaco();
      if (!failure || failure.origin?.scriptId !== id) {
        monaco.editor.setModelMarkers(model, MARKER_OWNER, []);
        return;
      }
      const location = parseTraceback(failure.traceback);
      if (!location) return;
      const line = Math.min(editorLine(location, failure.origin.lineOffset), model.getLineCount());
      monaco.editor.setModelMarkers(model, MARKER_OWNER, [
        {
          severity: monaco.MarkerSeverity.Error,
          message: failure.message,
          startLineNumber: line,
          endLineNumber: line,
          startColumn: 1,
          endColumn: model.getLineMaxColumn(line),
        },
      ]);
      editor.revealLineInCenterIfOutsideViewport(line);
    });
  }, [lastExecutionError.value, id]);

  const label = doc ? `${doc.dirty ? '● ' : ''}${doc.path ?? doc.title}` : id;
  const conflicted = diskConflicts.value.includes(id);

  return (
    <div
      class="script-tab"
      style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '4px 8px',
          borderBottom: '1px solid var(--vscode-panel-border)',
        }}
      >
        <button
          class="btn"
          onClick={() => run(editorRef.current?.getValue() ?? scriptText(id))}
          disabled={busy.value}
          title={m.script_run_tip()}
        >
          <i class="codicon codicon-play" aria-hidden="true" /> {m.script_run()}
        </button>
        <button
          class="btn"
          onClick={runSelection}
          disabled={busy.value}
          title={m.script_run_selection_tip()}
        >
          <i class="codicon codicon-run-below" aria-hidden="true" /> {m.script_selection()}
        </button>
        <button
          class="btn"
          onClick={() => {
            setNotice(null);
            void runFile(id).catch((error: unknown) =>
              setNotice(error instanceof Error ? error.message : String(error)),
            );
          }}
          disabled={busy.value}
          title={m.script_run_file_tip()}
        >
          <i class="codicon codicon-run-all" aria-hidden="true" /> {m.script_file()}
        </button>
        {busy.value && (
          <button
            class="btn"
            onClick={interrupt}
            title={m.script_interrupt_tip()}
            style={{ color: 'var(--vscode-errorForeground)' }}
          >
            <i class="codicon codicon-debug-stop" aria-hidden="true" /> {m.script_interrupt()}
          </button>
        )}
        <button class="btn" onClick={() => void saveScript(id)} title={m.script_save_tip()}>
          <i class="codicon codicon-save" aria-hidden="true" /> {m.prompt_save()}
        </button>
        <button class="btn" onClick={() => void saveScript(id, true)} title={m.script_save_as()}>
          {m.script_save_as()}
        </button>
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontSize: '11px',
            color: 'var(--vscode-descriptionForeground)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={label}
        >
          {label}
        </span>
      </div>

      {/* **Non-modal** banner: the file changed while the buffer had changed too. Nothing is
          decided on the user's behalf, and nothing interrupts them — they can keep writing and
          decide later. */}
      {conflicted && (
        <div
          role="status"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '4px 10px',
            fontSize: '12px',
            background: 'var(--vscode-inputValidation-warningBackground, #4d3800)',
            borderBottom: '1px solid var(--vscode-panel-border)',
          }}
        >
          <i class="codicon codicon-warning" aria-hidden="true" />
          <span style={{ flex: 1 }}>{m.script_disk_changed_banner()}</span>
          <button
            class="btn"
            onClick={() => {
              void reloadFromDisk(id).catch((error: unknown) =>
                setNotice(error instanceof Error ? error.message : String(error)),
              );
            }}
          >
            {m.prompt_reload()}
          </button>
          <button
            class="btn"
            onClick={() => {
              void keepMyVersion(id).catch((error: unknown) => console.error(error));
            }}
          >
            {m.script_disk_keep()}
          </button>
        </div>
      )}

      <div ref={hostRef} style={{ flex: 1, minHeight: 0 }} />

      <div
        style={{
          borderTop: '1px solid var(--vscode-panel-border)',
          padding: '2px 10px',
          fontSize: '11px',
          color: 'var(--vscode-descriptionForeground)',
          display: 'flex',
          gap: '12px',
        }}
      >
        <span>
          {m.script_position({ line: position.lineNumber, column: position.column })}
        </span>
        <span>Python</span>
        {busy.value && <span>{m.script_running()}</span>}
        {notice && <span style={{ color: 'var(--vscode-errorForeground)' }}>{notice}</span>}
      </div>
    </div>
  );
}
