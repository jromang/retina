// Command palette (Ctrl+Shift+P) — port of gui/palette.py.
//
// What is particular about it in Retina, and is kept as is: every entry displays
// **the equivalent Python line** on a second line, and Ctrl+C copies it without executing. This is
// the mechanism that teaches the API by clicking — the palette is as much a living
// documentation as a launcher.
//
// The 115 processes are injected into it on the same footing as the commands: searching "decon"
// must find Deconvolution, not only the menu entries.

import { formatShortcut } from './keybindings';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';

import { processes } from '../state/store';
import { baseCommands, fuzzyScore, processCommands, type Command } from './commands';
import { client } from '../api/client';
import { TablerIcon } from './TablerIcon';

interface Props {
  onClose: () => void;
}

export function CommandPalette({ onClose }: Props) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const [perspectives, setPerspectives] = useState<string[]>([]);
  useEffect(() => {
    void client
      .call<string[]>('layout.perspectives')
      .then(setPerspectives)
      .catch(() => undefined);
  }, []);

  const all = useMemo(
    () => [...baseCommands(perspectives), ...processCommands(processes.value)],
    [processes.value, perspectives],
  );

  const results = useMemo(() => {
    const scored: Array<{ command: Command; score: number; rank: number }> = [];
    all.forEach((command, rank) => {
      const score = fuzzyScore(`${command.category} ${command.title}`, query);
      if (score !== null) scored.push({ command, score, rank });
    });
    // On equal scores, insertion order breaks the tie: the ranking stays stable from one keystroke
    // to the next, which keeps the entries from jumping under the cursor.
    scored.sort((a, b) => b.score - a.score || a.rank - b.rank);
    return scored.slice(0, 40).map((entry) => entry.command);
  }, [all, query]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    setSelected(0);
  }, [query]);

  useEffect(() => {
    listRef.current
      ?.querySelector('[aria-selected="true"]')
      ?.scrollIntoView({ block: 'nearest' });
  }, [selected]);

  const runAt = (index: number) => {
    const command = results[index];
    if (!command) return;
    onClose();
    command.run();
  };

  const onKeyDown = (event: KeyboardEvent) => {
    switch (event.key) {
      case 'Escape':
        event.preventDefault();
        onClose();
        break;
      case 'ArrowDown':
        event.preventDefault();
        setSelected((i) => Math.min(i + 1, results.length - 1));
        break;
      case 'ArrowUp':
        event.preventDefault();
        setSelected((i) => Math.max(i - 1, 0));
        break;
      case 'Enter':
        event.preventDefault();
        runAt(selected);
        break;
      case 'c':
        // Ctrl+C copies the code without executing — one leaves with the line, not the effect.
        if (event.ctrlKey) {
          const python = results[selected]?.python;
          if (python) {
            event.preventDefault();
            void navigator.clipboard?.writeText(python);
            onClose();
          }
        }
        break;
      default:
        break;
    }
  };

  return (
    <div class="palette-scrim" onMouseDown={onClose}>
      <div class="palette" onMouseDown={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={query}
          placeholder={m.palette_placeholder()}
          onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
          onKeyDown={onKeyDown}
        />
        <div class="palette-list" ref={listRef}>
          {results.length === 0 && (
            <div class="palette-item" style={{ color: 'var(--vscode-descriptionForeground)' }}>
              {m.palette_no_results()}
            </div>
          )}
          {results.map((command, index) => (
            <div
              key={command.id}
              class="palette-item"
              aria-selected={index === selected}
              onMouseEnter={() => setSelected(index)}
              onClick={() => runAt(index)}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {command.icon ? <TablerIcon name={command.icon} /> : null}
                <span>
                  <span style={{ color: 'var(--vscode-descriptionForeground)' }}>
                    {command.category} :{' '}
                  </span>
                  {command.title}
                </span>
              </span>
              {command.shortcut && <span class="shortcut">{formatShortcut(command.shortcut)}</span>}
              {command.python && <span class="python">{command.python}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
