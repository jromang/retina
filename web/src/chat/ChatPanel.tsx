// Assistant panel — a conversation with the user's own Claude Code.
//
// Three screens come before the conversation, derived from the server's `chat.status`: Claude
// Code absent (install commands), present but not logged in (/login guidance), MCP endpoint
// absent (`--no-mcp`). The fourth state is the conversation itself: prose bubbles, collapsible
// tool lines, input at the bottom. All the state lives in `chat.ts` — this file is only
// rendering.

import { useEffect, useRef, useState } from 'preact/hooks';

import { m } from '../paraglide/messages';
import {
  type ChatBlock,
  type ChatStatus,
  chatBlocks,
  chatBusy,
  chatStatus,
  interruptChat,
  newConversation,
  refreshChatStatus,
  sendChat,
  toolLabel,
} from './chat';

const INSTALL_COMMANDS = [
  { label: () => m.chat_install_hint_macos_linux(), command: 'curl -fsSL https://claude.ai/install.sh | bash' },
  { label: () => m.chat_install_hint_windows(), command: 'irm https://claude.ai/install.ps1 | iex' },
];

function CopyableCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', minWidth: 0 }}>
      <code
        style={{
          flex: 1,
          overflow: 'auto hidden',
          whiteSpace: 'nowrap',
          padding: '4px 6px',
          background: 'var(--vscode-textCodeBlock-background)',
          borderRadius: '3px',
          font: '11px var(--retina-font-mono)',
          userSelect: 'text',
        }}
      >
        {command}
      </code>
      <button
        class="btn"
        onClick={() => {
          void navigator.clipboard?.writeText(command).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}
      >
        {copied ? m.chat_copied() : m.chat_copy()}
      </button>
    </div>
  );
}

function Gate({ title, children }: { title: string; children: preact.ComponentChildren }) {
  return (
    <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <strong>{title}</strong>
      {children}
      <button class="btn" onClick={() => void refreshChatStatus()}>
        {m.chat_recheck()}
      </button>
    </div>
  );
}

function ToolLine({ block }: { block: ChatBlock }) {
  const [open, setOpen] = useState(false);
  const label = toolLabel(block.tool ?? '', block.args);
  const details = block.args && Object.keys(block.args).length > 0;
  return (
    <div style={{ color: 'var(--vscode-descriptionForeground)' }}>
      <button
        onClick={() => details && setOpen(!open)}
        style={{
          background: 'none', border: 'none', color: 'inherit', font: 'inherit',
          cursor: details ? 'pointer' : 'default', padding: 0, textAlign: 'left',
        }}
      >
        <i class={`codicon codicon-${details && open ? 'chevron-down' : 'tools'}`} aria-hidden="true" />{' '}
        {label}
      </button>
      {open && details && (
        <pre style={{ margin: '2px 0 2px 18px', whiteSpace: 'pre-wrap' }}>
          {JSON.stringify(block.args, null, 2)}
        </pre>
      )}
    </div>
  );
}

function Bubble({ block }: { block: ChatBlock }) {
  switch (block.kind) {
    case 'user':
      return (
        <div
          style={{
            alignSelf: 'flex-end',
            maxWidth: '90%',
            padding: '5px 9px',
            borderRadius: '8px',
            background: 'var(--vscode-button-background)',
            color: 'var(--vscode-button-foreground)',
            whiteSpace: 'pre-wrap',
          }}
        >
          {block.text}
        </div>
      );
    case 'text':
      return <div style={{ whiteSpace: 'pre-wrap' }}>{block.text}</div>;
    case 'tool_call':
      return <ToolLine block={block} />;
    case 'tool_result':
      return block.ok === false ? (
        <div style={{ color: 'var(--vscode-errorForeground)', fontSize: '11px' }}>
          <i class="codicon codicon-warning" aria-hidden="true" /> {m.chat_tool_result_error()}{' '}
          {block.text}
        </div>
      ) : null; // a successful tool result is noise: the assistant comments on it itself
    case 'turn_done':
      return (
        <div style={{ color: 'var(--vscode-descriptionForeground)', fontStyle: 'italic' }}>
          {block.text}
        </div>
      );
    case 'error':
      return <div style={{ color: 'var(--vscode-errorForeground)' }}>{block.text}</div>;
    default:
      return null;
  }
}

function Conversation({ status }: { status: ChatStatus }) {
  const endRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState('');

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [chatBlocks.value]);

  const submit = () => {
    const text = draft;
    setDraft('');
    void sendChat(text);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: '8px', padding: '3px 8px',
          color: 'var(--vscode-descriptionForeground)', fontSize: '11px',
          borderBottom: '1px solid var(--vscode-panel-border)',
        }}
      >
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {m.chat_version({ version: status.version ?? '' })}
          {status.subscription ? ` · ${m.chat_subscription({ plan: status.subscription })}` : ''}
          {/* Newer than what we tested: warn without blocking — the format is stable in
              practice, and refusing would cost more than the risk covered. */}
          {status.version_untested && (
            <span title={m.chat_version_untested()} style={{ marginLeft: '5px' }}>
              <i class="codicon codicon-info" aria-hidden="true" />
            </span>
          )}
        </span>
        <button
          class="btn"
          title={m.chat_new()}
          onClick={() => void newConversation()}
        >
          <i class="codicon codicon-clear-all" aria-hidden="true" />
        </button>
      </div>

      <div
        style={{
          flex: 1, overflowY: 'auto', padding: '8px 10px',
          display: 'flex', flexDirection: 'column', gap: '6px',
          font: '12px/1.5 var(--vscode-font-family)', userSelect: 'text',
        }}
      >
        {chatBlocks.value.map((block) => (
          <Bubble key={block.id} block={block} />
        ))}
        {chatBusy.value && (
          <div style={{ color: 'var(--vscode-descriptionForeground)', fontStyle: 'italic' }}>
            <i class="codicon codicon-loading codicon-modifier-spin" aria-hidden="true" />{' '}
            {m.chat_busy()}
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div style={{ display: 'flex', gap: '6px', padding: '8px', borderTop: '1px solid var(--vscode-panel-border)' }}>
        <textarea
          value={draft}
          placeholder={m.chat_placeholder()}
          onInput={(event) => setDraft((event.target as HTMLTextAreaElement).value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          rows={2}
          style={{
            flex: 1, resize: 'none',
            background: 'var(--vscode-input-background)',
            color: 'var(--vscode-input-foreground)',
            border: '1px solid var(--vscode-input-border, transparent)',
            borderRadius: '3px', padding: '5px 7px', font: '12px var(--vscode-font-family)',
          }}
        />
        {chatBusy.value ? (
          <button class="btn" onClick={() => void interruptChat()}>
            {m.chat_stop()}
          </button>
        ) : (
          <button class="btn" disabled={!draft.trim()} onClick={submit}>
            {m.chat_send()}
          </button>
        )}
      </div>
    </div>
  );
}

export function ChatPanel() {
  useEffect(() => {
    // The probe (version + auth) only runs when the panel opens: the `hello` status is enough
    // as long as nobody is looking.
    void refreshChatStatus();
  }, []);

  const status = chatStatus.value;
  if (status === null) {
    return <div style={{ padding: '14px', color: 'var(--vscode-descriptionForeground)' }}>…</div>;
  }
  if (!status.installed) {
    return (
      <Gate title={m.chat_install_title()}>
        <span>{m.chat_install_body()}</span>
        {INSTALL_COMMANDS.map((entry) => (
          <div key={entry.command} style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <span style={{ fontSize: '11px', color: 'var(--vscode-descriptionForeground)' }}>
              {entry.label()}
            </span>
            <CopyableCommand command={entry.command} />
          </div>
        ))}
      </Gate>
    );
  }
  if (!status.version_supported) {
    return (
      <Gate title={m.chat_version_old_title()}>
        <span>
          {m.chat_version_old_body({
            min: status.min_version,
            version: status.version ?? '?',
          })}
        </span>
        <CopyableCommand command="claude update" />
      </Gate>
    );
  }
  if (status.authenticated === false) {
    return (
      <Gate title={m.chat_login_title()}>
        <span>{m.chat_login_body({ command: 'claude' })}</span>
      </Gate>
    );
  }
  if (!status.mcp_available) {
    return (
      <Gate title={m.panel_chat()}>
        <span>{m.chat_no_mcp()}</span>
      </Gate>
    );
  }
  return <Conversation status={status} />;
}
