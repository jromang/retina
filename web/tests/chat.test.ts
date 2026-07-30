// Assistant panel state: turning server events into displayable blocks.
//
// The contract held here: streamed prose merges into one bubble per turn (not one block per
// delta), tool calls become readable lines, and an unknown event type — the CLI stream is not
// contractual — is ignored without breaking the panel.

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.stubGlobal('location', { search: '', host: '127.0.0.1', protocol: 'http:' });
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined });

const { applyEvent, chatBlocks, chatBusy, failureText, toolLabel } = await import(
  '../src/chat/chat',
);

beforeEach(() => {
  chatBlocks.value = [];
  chatBusy.value = false;
});

describe('applyEvent', () => {
  it('merges the text deltas of the same turn into a single bubble', () => {
    applyEvent({ type: 'turn_started', turn: 1 });
    applyEvent({ type: 'text_delta', turn: 1, text: 'Looking at ' });
    applyEvent({ type: 'text_delta', turn: 1, text: 'the session.' });

    const text = chatBlocks.value.filter((b) => b.kind === 'text');
    expect(text).toHaveLength(1);
    expect(text[0]?.text).toBe('Looking at the session.');
    expect(chatBusy.value).toBe(true);
  });

  it('splits prose that a tool call interrupts', () => {
    applyEvent({ type: 'text_delta', turn: 1, text: 'Before.' });
    applyEvent({ type: 'tool_call', turn: 1, tool: 'get_state', args: {} });
    applyEvent({ type: 'text_delta', turn: 1, text: 'After.' });

    expect(chatBlocks.value.map((b) => b.kind)).toEqual(['text', 'tool_call', 'text']);
  });

  it('closes the turn and reports an interruption', () => {
    applyEvent({ type: 'turn_started', turn: 1 });
    applyEvent({ type: 'turn_done', turn: 1, status: 'interrupted' });

    expect(chatBusy.value).toBe(false);
    expect(chatBlocks.value.at(-1)?.kind).toBe('turn_done');
  });

  it('ignores an unknown type without breaking anything', () => {
    applyEvent({ type: 'future_invention', turn: 1 });
    expect(chatBlocks.value).toHaveLength(0);
  });

  it('empties the transcript on cleared', () => {
    applyEvent({ type: 'text_delta', turn: 1, text: 'x' });
    applyEvent({ type: 'cleared' });
    expect(chatBlocks.value).toHaveLength(0);
  });
});

describe('toolLabel', () => {
  it('names the targeted process when there is one', () => {
    expect(toolLabel('apply_process', { process_id: 'HistogramTransformation' })).toContain(
      'HistogramTransformation',
    );
  });

  it('has a generic fallback for any tool', () => {
    expect(toolLabel('pipeline', {})).toContain('pipeline');
  });
});

describe('named failure reasons', () => {
  it('explains an unparsed stream rather than returning a bare error', () => {
    applyEvent({ type: 'turn_done', turn: 1, status: 'error', reason: 'unparsed_stream' });

    const last = chatBlocks.value.at(-1);
    expect(last?.kind).toBe('error');
    // The text has to say what to do: that is the whole point of naming the reason.
    expect(last?.text).toMatch(/Retina/);
  });

  it('carries the CLI message through when there is no reason', () => {
    applyEvent({ type: 'turn_done', turn: 1, status: 'error', error: 'quota exceeded' });
    expect(chatBlocks.value.at(-1)?.text).toContain('quota exceeded');
  });

  it('invents nothing for an unknown reason', () => {
    expect(failureText('reason_from_the_future')).toContain('reason_from_the_future');
  });
});
