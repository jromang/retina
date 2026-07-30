// Console panel: transcript on top, Monaco editor at the bottom.
//
// This is deliberately not a terminal. A REPL attached to live state needs things a terminal
// emulator does not provide: collapsing a traceback, clicking an echo line to recall it,
// selecting multi-line text cleanly. Hence a DOM document.
//
// The echo of interface actions (`# ⟵ GUI: app.zoom_in()`) is inserted into that same stream:
// this is what makes the console a replayable session log, not just a prompt. It gets there
// through `connectTranscript`, at module level — the panel is only a view, and the echo keeps
// accumulating while it is closed.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { newScript } from '../scripts/scripts';
import '../styles/console.css';
import { colorizePython } from './highlight';
import { scriptFromBlocks } from './historyScript';
import { nextMatch } from './historyNav';
import {
  blocks,
  busy,
  clearTranscript,
  execute,
  history,
  interrupt,
  type Block,
} from './transcript';

const MAX_INPUT_LINES = 12;
/** Tolerance for "stuck to the bottom": pixel-exact scrolling is not something one aims at. */
const STICK_THRESHOLD = 8;

/**
 * Syntax-highlighted Python code — or plain text as long as Monaco is not loaded.
 *
 * The HTML comes from `monaco.editor.colorize`, which escapes its input: that is what makes
 * `dangerouslySetInnerHTML` legitimate here. Nothing else may be injected into this span.
 */
function PyCode({ text }: { text: string }) {
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    const pending = colorizePython(text);
    if (!pending) {
      setHtml(null);
      return;
    }
    let live = true;
    void pending.then((result) => {
      if (live) setHtml(result);
    });
    return () => {
      live = false;
    };
  }, [text]);

  if (html === null) return <>{text}</>;
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

/** A long traceback is collapsed: one wants the last line, not thirty. */
function Collapsible({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const lines = text.split('\n');
  if (lines.length <= 12) return <>{text}</>;
  const summary = lines.filter((line) => line.trim()).at(-1) ?? lines[0];
  return (
    <>
      <button class="console-collapse" onClick={() => setOpen(!open)}>
        <i class={`codicon codicon-chevron-${open ? 'down' : 'right'}`} aria-hidden="true" />{' '}
        {open ? m.console_collapse() : summary}
      </button>
      {open && <div>{text}</div>}
    </>
  );
}

/** Gutter markers for an entry: `>>>` on the first line, `...` on the following ones. */
function promptGutter(text: string): string {
  const lines = text.split('\n').length;
  return ['>>>', ...Array<string>(lines - 1).fill('...')].join('\n');
}

function BlockRow({ block, onRecall }: { block: Block; onRecall: (code: string) => void }) {
  if (block.kind === 'input') {
    return (
      <div class="console-block is-input">
        <span class="console-gutter">{promptGutter(block.text)}</span>
        <span class="console-body">
          <PyCode text={block.text} />
        </span>
      </div>
    );
  }

  if (block.kind === 'result') {
    return (
      <div class="console-block is-result">
        <span class="console-gutter">{`Out[${block.count ?? ''}]:`}</span>
        <span class="console-body">{block.text}</span>
      </div>
    );
  }

  if (block.kind === 'echo') {
    return (
      <div class="console-block is-echo">
        <button class="console-echo" onClick={() => onRecall(block.text)} title={m.console_recall_tip()}>
          <span class="console-echo-prefix">{'# ⟵ GUI: '}</span>
          <PyCode text={block.text} />
        </button>
      </div>
    );
  }

  const collapsible = block.kind === 'stdout' || block.kind === 'stderr';
  return (
    <div class={`console-block is-${block.kind}`}>
      <span class="console-body is-full">
        {collapsible ? <Collapsible text={block.text} /> : block.text}
      </span>
    </div>
  );
}

function Transcript({ onRecall }: { onRecall: (code: string) => void }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // True as long as the user has not scrolled back up. A `ref` and not a state: the value is
  // read in the scroll effect, not rendered.
  const stick = useRef(true);
  const [detached, setDetached] = useState(false);

  const atBottom = (node: HTMLDivElement) =>
    node.scrollHeight - node.scrollTop - node.clientHeight <= STICK_THRESHOLD;

  const scrollToBottom = () => {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
    stick.current = true;
    setDetached(false);
  };

  // Follow the output **only** when already at the bottom: otherwise re-reading the start of a
  // traceback while a stacking run prints became impossible, the view jumped on every line.
  useEffect(() => {
    if (stick.current) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [blocks.value]);

  // The transcript height does not depend on its content alone: the prompt grows with the code
  // typed into it, and the bottom zone is resized with the mouse. Without this catch-up,
  // writing a second line in the prompt pushed the last output under it, with no way to see it
  // again.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      if (stick.current) node.scrollTop = node.scrollHeight;
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      class="console-scroll"
      ref={scrollRef}
      onScroll={(event) => {
        const node = event.currentTarget as HTMLDivElement;
        stick.current = atBottom(node);
        setDetached(!stick.current);
      }}
    >
      <div class="console-transcript">
        {blocks.value.map((block) => (
          <BlockRow key={block.id} block={block} onRecall={onRecall} />
        ))}
      </div>
      {detached && (
        <button class="console-jump-bottom" title={m.console_jump_bottom()} onClick={scrollToBottom}>
          <i class="codicon codicon-arrow-down" aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

export function ConsolePanel() {
  const hostRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<any>(null);
  const historyIndex = useRef<number | null>(null);
  /** What the user had typed when navigation started — both prefix and the way back. */
  const historyPrefix = useRef('');
  /** True for the duration of a navigation `setValue`, so as not to reset the prefix. */
  const applyingHistory = useRef(false);
  const [notice, setNotice] = useState<string | null>(null);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flash = (message: string) => {
    setNotice(message);
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(null), 4000);
  };

  const recall = (code: string) => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.setValue(code);
    editor.focus();
    editor.setPosition({ lineNumber: editor.getModel().getLineCount(), column: 1e6 });
  };

  useEffect(() => {
    const host = hostRef.current;
    if (!host || editorRef.current) return;
    let disposed = false;
    let created: { dispose: () => void } | null = null;

    // Dynamic import: Monaco alone weighs ~2.5 MB. The console is not always open, so it is
    // loaded only at its first appearance — the shell itself starts light.
    void import('./monaco').then(async ({ setupMonaco }) => {
      if (disposed) return;
      const monaco = setupMonaco();
      created = mountEditor(host, monaco);
      // The transcript is highlighted with the same tokenizer and theme as the prompt.
      const { registerMonaco } = await import('./highlight');
      registerMonaco(monaco);
    });

    return () => {
      disposed = true;
      created?.dispose();
      editorRef.current = null;
      if (noticeTimer.current) clearTimeout(noticeTimer.current);
    };
  }, []);

  function mountEditor(host: HTMLDivElement, monaco: typeof import('monaco-editor')) {
    const editor = monaco.editor.create(host, {
      value: '',
      language: 'python',
      theme: 'retina-dark',
      automaticLayout: true,
      minimap: { enabled: false },
      // `>>>` then `...`: the REPL markers are Monaco's line numbers. Drawing them ourselves in
      // a neighboring span — which is what the previous version did — gave a single `>>>` for a
      // ten-line entry, and nothing stayed aligned.
      lineNumbers: (line) => (line === 1 ? '>>>' : '...'),
      lineNumbersMinChars: 4,
      glyphMargin: false,
      folding: false,
      lineDecorationsWidth: 4,
      renderLineHighlight: 'none',
      scrollBeyondLastLine: false,
      overviewRulerLanes: 0,
      scrollbar: { vertical: 'auto', horizontal: 'hidden' },
      fontFamily: 'var(--retina-font-mono)',
      fontSize: 12,
      padding: { top: 4, bottom: 4 },
      wordWrap: 'on',
      contextmenu: false,
    });
    editorRef.current = editor;

    // `editor.addCommand` registers the shortcut in Monaco's **global** service, not on this
    // editor: without a context key, this prompt's Enter also applied to the script editor,
    // where one could therefore no longer create a line. The third argument is the activation
    // condition, and that is what makes the shortcut local.
    editor.createContextKey('retinaConsolePrompt', true);
    const ICI = 'retinaConsolePrompt';
    // Second key, so that Ctrl+C exists **only** during an execution (see below).
    const busyKey = editor.createContextKey('retinaConsoleBusy', busy.value);
    const unsubscribeBusy = busy.subscribe((value) => busyKey.set(value));

    // Height that follows the content, up to twelve lines. Measured by Monaco: the previous
    // version multiplied the line count by 18 px, a figure matching nobody's font and clipping
    // the last line as soon as it wrapped.
    const resize = () => {
      const lineHeight = editor.getOption(monaco.editor.EditorOption.lineHeight);
      const max = MAX_INPUT_LINES * lineHeight + 8;
      host.style.height = `${Math.min(editor.getContentHeight(), max)}px`;
    };
    editor.onDidContentSizeChange(resize);
    resize();

    // A keystroke that is not navigation cancels the current history filter.
    editor.onDidChangeModelContent(() => {
      if (applyingHistory.current) return;
      historyIndex.current = null;
      historyPrefix.current = editor.getValue();
    });

    const applyHistory = (text: string) => {
      applyingHistory.current = true;
      editor.setValue(text);
      editor.setPosition({ lineNumber: editor.getModel()?.getLineCount() ?? 1, column: 1e6 });
      applyingHistory.current = false;
    };

    // Enter executes; Shift+Enter inserts a new line. This is the notebook convention, and it
    // avoids the multi-line block trap of the classic REPL.
    editor.addCommand(monaco.KeyCode.Enter, () => {
      // Test first: clearing the prompt **and then** discovering that `execute` refuses
      // silently threw away what the user had just written.
      if (busy.value) {
        flash(m.console_busy_notice());
        return;
      }
      const code = editor.getValue();
      editor.setValue('');
      historyIndex.current = null;
      historyPrefix.current = '';
      void execute(code);
    }, ICI);
    editor.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.Enter, () => {
      editor.trigger('keyboard', 'type', { text: '\n' });
    }, ICI);

    // Arrow keys: history navigation when the cursor is at the edge of the text, otherwise
    // normal movement — without which a multi-line block could no longer be edited.
    //
    // What is already typed filters the search (`app.` then Up only offers lines starting with
    // `app.`), the IPython and shell convention.
    editor.addCommand(monaco.KeyCode.UpArrow, () => {
      const position = editor.getPosition();
      if (position && position.lineNumber > 1) {
        editor.trigger('keyboard', 'cursorUp', {});
        return;
      }
      if (historyIndex.current === null) historyPrefix.current = editor.getValue();
      const index = nextMatch(history.value, historyIndex.current, historyPrefix.current, 'older');
      if (index === null) return; // nothing older left: keep what is displayed
      historyIndex.current = index;
      applyHistory(history.value[index] ?? '');
    }, ICI);
    editor.addCommand(monaco.KeyCode.DownArrow, () => {
      const model = editor.getModel();
      const position = editor.getPosition();
      if (position && model && position.lineNumber < model.getLineCount()) {
        editor.trigger('keyboard', 'cursorDown', {});
        return;
      }
      if (historyIndex.current === null) return;
      const index = nextMatch(history.value, historyIndex.current, historyPrefix.current, 'newer');
      if (index === null) {
        // Back to the present: restore the buffer navigation had set aside.
        historyIndex.current = null;
        applyHistory(historyPrefix.current);
        return;
      }
      historyIndex.current = index;
      applyHistory(history.value[index] ?? '');
    }, ICI);

    // Ctrl+C interrupts — but **never** at the expense of copying: the condition requires an
    // execution in progress and the absence of a selection. `editorHasSelection` is a Monaco
    // context key, hence always up to date.
    editor.addCommand(
      monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyC,
      () => interrupt(),
      `${ICI} && retinaConsoleBusy && !editorHasSelection`,
    );
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyL, () => clearTranscript(), ICI);

    return {
      dispose: () => {
        unsubscribeBusy();
        editor.dispose();
      },
    };
  }

  return (
    <div class="console">
      <div class="console-toolbar">
        <button
          class="console-action"
          onClick={() => newScript(scriptFromBlocks(blocks.value, new Date().toLocaleString()))}
          title={m.console_new_script_tip()}
        >
          <i class="codicon codicon-file-code" aria-hidden="true" />
        </button>
        {busy.value && (
          <button class="console-action is-danger" onClick={interrupt} title={m.console_interrupt_tip()}>
            <i class="codicon codicon-debug-stop" aria-hidden="true" />
          </button>
        )}
        <button class="console-action" onClick={clearTranscript} title={m.console_clear_tip()}>
          <i class="codicon codicon-clear-all" aria-hidden="true" />
        </button>
      </div>

      <Transcript onRecall={recall} />

      {notice && <div class="console-notice">{notice}</div>}

      <div class={`console-input-row${busy.value ? ' is-busy' : ''}`}>
        <div class="console-input" ref={hostRef} />
      </div>
    </div>
  );
}
