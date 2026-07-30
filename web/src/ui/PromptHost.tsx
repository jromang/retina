// Rendering of the input/confirmation modal. Mounted once by the workbench.
//
// The styling reuses `.palette-scrim`: it is already the shell's modal box, and having two that
// look alike without being identical would be worse than sharing one.

import { useEffect, useRef } from 'preact/hooks';

import { m } from '../paraglide/messages';
import { promptRequest } from './prompts';

export function PromptHost() {
  const request = promptRequest.value;
  const inputRef = useRef<HTMLInputElement>(null);
  const selectRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    if (request?.kind === 'text') inputRef.current?.select();
  }, [request]);

  if (!request) return null;

  const submit = () => {
    if (request.kind === 'text') request.resolve(inputRef.current?.value ?? '');
    else if (request.kind === 'choice') request.resolve(selectRef.current?.value ?? request.initial);
    else request.resolve('');
  };
  const cancel = () => request.resolve(null);

  return (
    <div class="palette-scrim" onMouseDown={(event) => event.target === event.currentTarget && cancel()}>
      <div
        class="palette"
        role="dialog"
        aria-modal="true"
        aria-label={request.title}
        style={{ padding: '14px 16px' }}
        onKeyDown={(event: KeyboardEvent) => {
          if (event.key === 'Escape') cancel();
          // Enter submits — including on a confirmation, where there is no field.
          else if (event.key === 'Enter') submit();
          else return;
          event.preventDefault();
          event.stopPropagation();
        }}
      >
        <p style={{ margin: '0 0 10px', fontSize: '13px' }}>{request.title}</p>
        {request.kind === 'text' && (
          <input
            ref={inputRef}
            type="text"
            value={request.initial}
            autoFocus
            style={{ width: '100%', marginBottom: '12px' }}
          />
        )}
        {request.kind === 'choice' && (
          <select
            ref={selectRef}
            value={request.initial}
            autoFocus
            style={{ width: '100%', marginBottom: '12px' }}
          >
            {(request.choices ?? []).map((choice) => (
              <option key={choice.value} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
        )}
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button class="btn" onClick={cancel}>
            {m.prompt_cancel()}
          </button>
          <button class="btn btn-primary" autoFocus={request.kind === 'confirm'} onClick={submit}>
            {request.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
