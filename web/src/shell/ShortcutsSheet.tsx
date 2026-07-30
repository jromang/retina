// Shortcuts cheat sheet — generated from the table, never written by hand.
//
// This is the visible counterpart of the design decision: since the keymap is *derived* from the
// command registry, the list displayed here cannot lie. A documentation page written by
// hand would have diverged at the first shortcut added.
//
// The contextual shortcuts (Ctrl+S, F5 in the script editor, laid down by Monaco) are
// outside the keymap but appear all the same, in their own section: they are the ones people look
// for the most, and hiding them would give a cheat sheet that is wrong by omission.

import { m } from '../paraglide/messages';
import { commandIndex, type Command } from './commands';
import { buildKeymap, chordKey, parseChord, shortcutParts } from './keybindings';
import { processes } from '../state/store';
import { shortcutsOpen } from './uiState';

function rows(): { chord: string; command: Command }[] {
  const index = commandIndex([], processes.value);
  const global = [...buildKeymap(index.values())].map(([chord, id]) => ({
    chord,
    command: index.get(id)!,
  }));
  const contextual = [...index.values()]
    .filter((command) => command.localShortcut && command.shortcut)
    .map((command) => ({ chord: chordKey(parseChord(command.shortcut!)!), command }));
  return [...global, ...contextual].filter((row) => row.command);
}

export function ShortcutsSheet() {
  if (!shortcutsOpen.value) return null;
  const close = () => {
    shortcutsOpen.value = false;
  };

  const groups = new Map<string, { chord: string; command: Command }[]>();
  for (const row of rows()) {
    const bucket = groups.get(row.command.category);
    if (bucket) bucket.push(row);
    else groups.set(row.command.category, [row]);
  }

  return (
    <div
      class="palette-scrim"
      onMouseDown={(event) => event.target === event.currentTarget && close()}
    >
      <div
        class="palette"
        role="dialog"
        aria-modal="true"
        aria-label={m.shortcuts_title()}
        tabIndex={-1}
        autoFocus
        onKeyDown={(event: KeyboardEvent) => {
          if (event.key !== 'Escape') return;
          event.preventDefault();
          close();
        }}
        style={{ padding: '14px 16px', maxHeight: '70vh', overflowY: 'auto' }}
      >
        <p style={{ margin: '0 0 12px', fontSize: '13px' }}>
          {m.shortcuts_lead()}
        </p>
        {[...groups.entries()].map(([category, entries]) => (
          <section key={category} style={{ marginBottom: '12px' }}>
            <h3 class="panel-section" style={{ margin: '0 0 4px' }}>
              {category}
            </h3>
            {entries.map(({ chord, command }) => (
              <div
                key={command.id}
                style={{ display: 'flex', gap: '8px', alignItems: 'baseline', padding: '2px 0' }}
              >
                <span style={{ flex: 1, fontSize: '12px' }}>{command.title}</span>
                <span style={{ display: 'flex', gap: '4px' }}>
                  {shortcutParts(chord).map((part) => (
                    <kbd
                      key={part}
                      style={{
                        font: '11px var(--retina-font-mono)',
                        background: 'var(--vscode-input-background)',
                        border: '1px solid var(--vscode-input-border)',
                        borderRadius: '3px',
                        padding: '1px 5px',
                      }}
                    >
                      {part}
                    </kbd>
                  ))}
                </span>
                {command.localShortcut && (
                  <span style={{ fontSize: '10px', color: 'var(--vscode-descriptionForeground)' }}>
                    {m.shortcuts_in_editor()}
                  </span>
                )}
              </div>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}
